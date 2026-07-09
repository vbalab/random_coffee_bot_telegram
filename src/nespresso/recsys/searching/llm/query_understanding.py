"""
Query understanding for Find search.

A single fast Haiku call turns a natural-language people-search query (Russian or
English) into a structured search plan with THREE parts:

  1. `is_valid_search` — safety gate. `false` for non-bona-fide queries (slurs,
     sexual/obscene or degrading wording about people, "find me a bad person"),
     which the caller turns into a plain "nothing found".
  2. `semantic_query` — a faithful, BILINGUAL (Russian + English) restatement of
     the search intent, for embedding + BM25. Profiles mix both languages
     (directory text is mostly Russian; index-time enrichment adds English
     glosses) and BM25 is exact-token (no stemming/translation), so a one-language
     query silently misses half the corpus. It restates + translates the query and
     widens it only SLIGHTLY (a few of the closest same-concept synonyms), never
     broadening into adjacent fields or naming employers — the profile index
     carries the heavier world-knowledge expansion on its own side.
  3. `filters` — structured constraints for boosting / filtering in OpenSearch.

It is **fallback-safe**: any error, timeout, or malformed response degrades to
`ParsedQuery(semantic_query=<raw text>, ...)` — i.e. today's behaviour — so a
flaky Claude API never breaks search. On that failure path a tiny deterministic
slur backstop still rejects the most egregious queries (the LLM moderator is
otherwise the primary gate).

The big static system prompt is large enough to be prompt-cached. To make caching
pay off (a 1-hour cache write costs 2x base input; it only amortizes at >=3
queries/hour), we attach a 1-hour `cache_control` ONLY once the rolling 60-minute
query count reaches `PARSER_CACHE_HOURLY_THRESHOLD`; below that we send uncached.

Forward-compatible: `program` / `class_year` / `gender` are extracted even though
the MyNES directory feed does not currently carry them — the moment that data
lands, the filters light up with zero code change.
"""

import json
import logging
import re
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from nespresso.core.configs.settings import settings
from nespresso.recsys.searching.llm.alerts import ReportLLMError
from nespresso.recsys.searching.llm.client import client
from nespresso.recsys.searching.llm.world_knowledge import WORLD_KNOWLEDGE

# MyNES controlled vocabularies (the directory exposes these as fixed enums).
# The parser maps free-text user phrasing onto these canonical values so they can
# be matched against the keyword fields we index.
_INDUSTRY_EXPERTISE = [
    "Образование",
    "Транспорт и логистика",
    "Производство",
    "Нефть и газ",
    "Недвижимость",
    "Металлургия и горнодобывающая промышленность",
    "Культура и искусство",
    "Здравоохранение и фармацевтика",
    "Отели и рестораны",
    "Сельское хозяйство",
    "IT, телеком",
    "Оптовая и розничная торговля",
    "Государственный сектор",
    "Развлечения",
    "Некоммерческие организации",
    "ЖКХ",
]
_PROFESSIONAL_EXPERTISE = [
    "Анализ данных",
    "Машинное обучение",
    "Корпоративные финансы",
    "Управление проектами",
    "Программирование",
    "Стартапы и инновации",
    "Отраслевая",
    "Управление продуктами",
    "По акциям",
    "Стратегия",
    "Риск-менеджмент",
    "Оценка активов",
    "Управление активами",
    "Эконометрика",
    "Маркетинг",
    "Предпринимательство",
    "Корпоративное управление",
    "Слияния и поглощения",
    "Венчурные инвестиции",
    "Трейдинг",
    "Коммерческие банки",
    "Структурированные финансы и деривативы",
    "Операционные процессы",
    "По инструментам с фиксированной доходностью",
    "Макроэкономическая",
    "Алготрейдинг",
    "Проектное финансирование",
    "Аналитика Центрального Банка",
    "Макроэкономика",
    "Investor Relations/Public Relations",
    "Политическая экономика и политология",
    "IT-консалтинг",
    "Продажи",
    "Прикладная микроэкономика",
    "Размещение ценных бумаг",
    "Казначейство (ALM)",
    "Экономическая теория",
    "Бухгалтерский учет и аудит",
    "Преподавание",
    "Стратегический консалтинг",
    "Финансовый консалтинг",
    "Blockchain и криптовалюты",
    "Волонтерство",
    "Журналистика",
]
_COUNTRY_EXPERTISE = [
    "Россия",
    "США",
    "Континентальная Европа",
    "Великобритания",
    "Азия",
    "Emerging markets",
    "Страны СНГ",
    "EMEA",
]

_INDUSTRY_SET = {v.casefold() for v in _INDUSTRY_EXPERTISE}
_PROFESSIONAL_SET = {v.casefold() for v in _PROFESSIONAL_EXPERTISE}
_COUNTRY_EXP_SET = {v.casefold() for v in _COUNTRY_EXPERTISE}

# NES study programs as they appear in the directory feed's `programs[].name`
# (full Russian names, not codes). The parser maps user phrasing onto these so a
# `program` filter exact-matches the indexed `f_program` keyword field.
_PROGRAMS = [
    "Магистр экономики",
    "Бакалавр экономики",
    "Мастер финансов",
    "Финансы, инвестиции, банки",
    "Экономика энергетики и природных ресурсов",
    "Мастер наук по финансам",
    "Мини-Мастер финансов",
    "Экономика и анализ данных",
    "Управление благосостоянием: экспертный уровень",
    "Мастер наук по экономике энергетики",
]
_PROGRAM_SET = {v.casefold(): v for v in _PROGRAMS}


def _bullets(values: list[str]) -> str:
    return "\n".join(f"- {v}" for v in values)


_SYSTEM_PROMPT = f"""\
You convert a single natural-language people-search query into a structured search \
plan for an alumni network of the New Economic School (NES / Российская \
экономическая школа, РЭШ) in Moscow. Queries come from alumni looking for other \
alumni and are written in Russian, English, or a mix.

Return a JSON object with THREE parts: `is_valid_search`, `semantic_query`, and \
`filters`. Every key is ALWAYS present.

## 1. is_valid_search  (safety gate — decide this first)
`true` for any good-faith search for an alum by professional or personal \
attributes (role, employer, skills, expertise, location, education, industry, \
name, interests) — even if vaguely or oddly phrased.
`false` ONLY when the query is NOT a bona-fide people search, for example:
- sexual, obscene, or degrading wording about a person — including slang, \
obfuscated, or wrapped forms (e.g. "найди мне шлюху среди выпускниц", "гондон", \
masked spelling, leetspeak);
- slurs, insults, harassment, or asking to find someone to demean ("плохой \
человек", "самый тупой выпускник", "лох", "враг");
- content that is clearly not a search for a peer by their attributes.
When `false`, set `semantic_query` to "" and every filter to null / []. When \
genuinely unsure, prefer `true` — do NOT block legitimate but unusual phrasing.

## 2. semantic_query
A faithful, natural-language restatement of the person sought — role, skills, \
expertise, specialization, and any qualifiers — written in BOTH Russian and \
English, because profiles mix both languages.
- Bilingual, ALWAYS. Give the core concept in Russian AND English (e.g. "инженер \
машинного обучения, machine learning engineer"). A one-language query silently \
misses half the corpus: BM25 is exact-token (no stemming or translation), so an \
English-only query cannot match a Russian profile, and vice versa.
- Preserve intent — do NOT shrink it. Keep every meaningful descriptor the user \
gave: seniority ("опытный / senior / experienced"), specialization ("в банках / in \
banking", "финтех / fintech"), the actual role and skills. Never boil a rich query \
down to one generic term.
- Restate, and widen only SLIGHTLY. Rephrase and TRANSLATE what the user asked \
for, then you MAY add a FEW (about 2-4) of the CLOSEST synonyms or the immediate \
parent category of the core concept, in both languages — e.g. "финансы" → also \
"финансовый сектор, finance, financial industry"; "HFT" → also "алготрейдинг, \
algorithmic trading". Do NOT broaden into ADJACENT fields ("финансы" must NOT add \
"trading"; "healthcare" must NOT add "biotech"), do NOT name specific employers \
(XTX, McKinsey, Сбербанк — those go in `company`), and keep the whole query TIGHT \
(roughly a dozen words, a natural phrase, NOT a long keyword dump) so it stays \
embedding-friendly.
- Do NOT widen a SPECIFIC role / title / skill query. Translate it to both \
languages but add NO synonyms or related skills — such roles are already pinned by \
the `role` / `professional_expertise` filters, and extra near-terms only pull in \
adjacent people and dilute precision. E.g. "data scientists" → JUST "дата-сайентист, \
data scientist" (NOT "+ анализ данных, машинное обучение, machine learning"); \
"продакт-менеджеры" → JUST "продакт-менеджер, product manager". Widen ONLY genuinely \
BROAD / vague queries (e.g. "кто из мира финансов", "HFT").
- Drop ONLY pure filler (найди, ищу, кто, find, …) and values already captured by \
a structured filter below (city, country, company, program, class year), which are \
matched precisely there. KEEP role / skill / expertise words even if they also \
fill a filter.
If the query is purely structured (e.g. only a program + year, or only an \
employer), set it to "".

Reference knowledge — use it ONLY to understand employer / term names that appear \
in the QUERY (so you can map them to the right category / filter). Do NOT copy \
these employer lists into `semantic_query`; restate only what the user actually \
asked for:

{WORLD_KNOWLEDGE}

## 3. filters
Structured constraints extracted from the query. Use `null` (or an empty array) \
for anything not present. NEVER invent values that aren't implied by the query.
- `program`: NES study program if named, chosen ONLY from this fixed list (output \
the EXACT canonical name; omit if no clear match). Map the conventional NES \
abbreviations / synonyms — Russian OR English: "МАЭ" / "MAE" / "Master of Arts \
in Economics" / "магистратура по экономике" → "Магистр экономики"; "МИФ" / "МФ" / \
"MiF" / "MaF" / "MAF" / "Master of Finance" / "Master of Arts in Finance" → \
"Мастер финансов"; "БАЭ" / "BAE" / "бакалавриат" → "Бакалавр экономики"; "ФИБ" / \
"FIB" → "Финансы, инвестиции, банки"; "ЭАД" / "EDS" / "Economics and Data \
Science" → "Экономика и анализ данных"; "Мини-МИФ" / "Mini-MiF" → "Мини-Мастер \
финансов"; "MSF" / "MSc Finance" / "MSc in Finance" → "Мастер наук по финансам":
{_bullets(_PROGRAMS)}
- `class_year`: 4-digit NES graduation/class year if given (e.g. 2002).
- `gender`: "male" if the query asks for men (мужчин, мужчины, парней, men, male); \
"female" for women (женщин, девушек, women, female); otherwise null.
- `city`: city if named, ALWAYS OUTPUT IN RUSSIAN — translate from English \
("London" → "Лондон", "New York" → "Нью-Йорк", "Moscow" → "Москва", "Boston" → \
"Бостон"). Profiles store city names in Russian, so an English city won't match.
- `country`: the person's country of RESIDENCE if named, in Russian. Do NOT use \
this for market/region expertise — that goes in `country_expertise`.
- `country_expertise`: regions/markets the person professionally specializes in, \
zero or more, chosen ONLY from this fixed list. Map "эксперт по рынку США / US \
market / американский рынок" → "США"; "Asian markets / Азия" → "Азия"; "emerging \
markets / развивающиеся рынки" → "Emerging markets"; "Европа / European markets" \
→ "Континентальная Европа"; "UK" → "Великобритания"; "СНГ" → "Страны СНГ":
{_bullets(_COUNTRY_EXPERTISE)}
- `company`: a specific employer/organization if named (e.g. "Сбербанк", "Yandex", \
"McKinsey").
- `role`: the job TITLE sought — what would be printed on the person's business \
card (data scientist, product manager, CEO, founder, consultant, trader, quant, \
analyst). Output it BILINGUALLY (Russian + English), comma-separated, because \
profiles list titles in both languages and this value is substring-matched against \
them — e.g. "data scientist, дата-сайентист"; "product manager, продакт-менеджер"; \
"CEO, генеральный директор, основатель"; "трейдер, trader". Keep each variant \
short. IMPORTANT — title vs domain: if the query instead names a professional \
FUNCTION or field of competence that matches a `professional_expertise` value \
below (продажи/sales, маркетинг/marketing, риск-менеджмент/risk, \
преподавание/teaching, M&A, asset management, …), put it in \
`professional_expertise` and leave `role` null. This holds EVEN when the query \
uses the person-noun form: "маркетолог/marketer" → professional_expertise \
"Маркетинг" (role null); "риск-менеджер/risk manager" → "Риск-менеджмент" (role \
null); "трейдер/trader" → "Трейдинг" (role null). Only set `role` for a job title \
that is NOT itself one of the expertise categories (data scientist, product \
manager, CEO, founder, consultant, quant). Pick exactly ONE home per concept — \
never both `role` and `professional_expertise` for the same word.
- `university`: a non-NES university where the person STUDIED (pre/post-NES \
education — bachelor/master/PhD), if named. Recognize it in education phrasings \
even when only the short name is given: "выпускник/учился/студент/закончил X", \
"degree/PhD/Master/MBA from X", "PhD из X", "защитил(ся) ... в X", "doctorate at \
X" → university = X (e.g. "PhD из Боккони" → "Боккони"; "учился в MIT" → "MIT"). \
This is the SCHOOL someone attended — do NOT confuse it with an employer: "работает \
в X" / "преподаёт в X" / "professor at X" is `company`, not `university`. Use a \
recognizable short form (e.g. "МГУ", "МФТИ", "ВШЭ", "MIT", "Боккони") AND repeat \
ONLY that short form + its abbreviation inside `semantic_query` (e.g. "ВШЭ, HSE"; \
"МГУ, MSU"). Do NOT put the full multi-word institutional name ("Высшая школа \
экономики", "Higher School of Economics", "Московский государственный университет") \
in `semantic_query`: those long names collide with the corpus's dominant \
vocabulary (this is an ECONOMICS-school network) and flood the match. The \
`university` filter already recalls profiles that spell the full name out.
- `industry_expertise`: zero or more values, chosen ONLY from this fixed list \
(translate the user's wording to the closest canonical Russian value; omit if no \
good match):
{_bullets(_INDUSTRY_EXPERTISE)}
- `professional_expertise`: zero or more values, chosen ONLY from this fixed list \
(map e.g. "data science"/"ML"/"машинное обучение" → "Машинное обучение" and \
"Анализ данных"; "M&A" → "Слияния и поглощения"; "венчур" → "Венчурные \
инвестиции"; "трейдер" → "Трейдинг"); omit if no good match:
{_bullets(_PROFESSIONAL_EXPERTISE)}

## Noise to drop
These appear in almost every query and carry no signal — never put them in \
`semantic_query` or any filter: выпускник, выпускники, \
выпускников, alumni, alum, РЭШ, NES, New Economic School, человек, людей, найди, \
найти, ищу, нужен, покажи, кто, find, search, looking for, someone, people, person.

## Examples
Query: "HFT"
{{"is_valid_search": true, "semantic_query": "высокочастотный трейдинг, \
high-frequency trading, HFT, алготрейдинг, algorithmic trading", \
"filters": {{"program": null, "class_year": null, "gender": null, "city": null, \
"country": null, "country_expertise": [], "company": null, "role": null, \
"university": null, "industry_expertise": [], "professional_expertise": \
["Трейдинг", "Алготрейдинг"]}}}}

Query: "кто из мира финансов"
{{"is_valid_search": true, "semantic_query": "финансы, финансовый сектор, finance, \
financial industry, инвестиции, investment", "filters": {{"program": null, \
"class_year": null, "gender": null, "city": null, "country": null, \
"country_expertise": [], "company": null, "role": null, "university": null, \
"industry_expertise": [], "professional_expertise": []}}}}

Query: "кто работал в Сбербанке"
{{"is_valid_search": true, "semantic_query": "", "filters": {{"program": null, \
"class_year": null, "gender": null, "city": null, "country": null, \
"country_expertise": [], "company": "Сбербанк", "role": null, "university": null, \
"industry_expertise": [], "professional_expertise": []}}}}

Query: "Найди самых опытных финансовых аналитиков"
{{"is_valid_search": true, "semantic_query": "опытный финансовый аналитик, \
experienced financial analyst, senior financial analyst", "filters": {{"program": \
null, "class_year": null, "gender": null, "city": null, "country": null, \
"country_expertise": [], "company": null, "role": null, "university": null, \
"industry_expertise": [], "professional_expertise": []}}}}

Query: "data scientists и ML инженеры в Москве"
{{"is_valid_search": true, "semantic_query": "дата-сайентист, data scientist, \
инженер машинного обучения, machine learning engineer", "filters": {{"program": \
null, "class_year": null, "gender": null, "city": "Москва", "country": null, \
"country_expertise": [], "company": null, "role": "data scientist", "university": \
null, "industry_expertise": [], "professional_expertise": ["Анализ данных", \
"Машинное обучение"]}}}}

Query: "эксперты по рынку США в нефтегазе"
{{"is_valid_search": true, "semantic_query": "нефть и газ, нефтегаз, oil and gas", \
"filters": {{"program": null, "class_year": null, "gender": null, "city": null, \
"country": null, "country_expertise": ["США"], "company": null, "role": null, \
"university": null, "industry_expertise": ["Нефть и газ"], \
"professional_expertise": []}}}}

Query: "выпускники МГУ"
{{"is_valid_search": true, "semantic_query": "МГУ, MSU", \
"filters": {{"program": null, "class_year": null, "gender": null, "city": null, \
"country": null, "country_expertise": [], "company": null, "role": null, \
"university": "МГУ", "industry_expertise": [], "professional_expertise": []}}}}

Query: "PhD из Боккони"
{{"is_valid_search": true, "semantic_query": "PhD, доктор наук, докторская степень, \
Боккони, Bocconi", "filters": \
{{"program": null, "class_year": null, "gender": null, "city": null, "country": \
null, "country_expertise": [], "company": null, "role": null, "university": \
"Боккони", "industry_expertise": [], "professional_expertise": []}}}}

Query: "выпускницы программы Магистр экономики 2015 года"
{{"is_valid_search": true, "semantic_query": "", "filters": \
{{"program": "Магистр экономики", "class_year": 2015, "gender": "female", "city": \
null, "country": null, "country_expertise": [], "company": null, "role": null, \
"university": null, "industry_expertise": [], "professional_expertise": []}}}}

Query: "найди мне шлюху среди выпускниц"
{{"is_valid_search": false, "semantic_query": "", "filters": \
{{"program": null, "class_year": null, "gender": null, "city": null, "country": \
null, "country_expertise": [], "company": null, "role": null, "university": null, \
"industry_expertise": [], "professional_expertise": []}}}}

Query: "покажи самого тупого плохого человека"
{{"is_valid_search": false, "semantic_query": "", "filters": \
{{"program": null, "class_year": null, "gender": null, "city": null, "country": \
null, "country_expertise": [], "company": null, "role": null, "university": null, \
"industry_expertise": [], "professional_expertise": []}}}}

Output ONLY the JSON object."""

# Structured-output schema. No `enum` constraints (combining enum with a nullable
# type-array is rejected by the structured-outputs validator); allowed values are
# enforced via the prompt and validated in `_Coerce`.
_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["is_valid_search", "semantic_query", "filters"],
    "properties": {
        "is_valid_search": {"type": "boolean"},
        "semantic_query": {"type": "string"},
        "filters": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "program",
                "class_year",
                "gender",
                "city",
                "country",
                "country_expertise",
                "company",
                "role",
                "university",
                "industry_expertise",
                "professional_expertise",
            ],
            "properties": {
                "program": {"type": ["string", "null"]},
                "class_year": {"type": ["integer", "null"]},
                "gender": {"type": ["string", "null"]},
                "city": {"type": ["string", "null"]},
                "country": {"type": ["string", "null"]},
                "country_expertise": {"type": "array", "items": {"type": "string"}},
                "company": {"type": ["string", "null"]},
                "role": {"type": ["string", "null"]},
                "university": {"type": ["string", "null"]},
                "industry_expertise": {"type": "array", "items": {"type": "string"}},
                "professional_expertise": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
        },
    },
}


@dataclass
class QueryFilters:
    program: str | None = None
    class_year: int | None = None
    gender: str | None = None
    city: str | None = None
    country: str | None = None
    country_expertise: list[str] = field(default_factory=list)
    company: str | None = None
    role: str | None = None
    university: str | None = None
    industry_expertise: list[str] = field(default_factory=list)
    professional_expertise: list[str] = field(default_factory=list)

    def IsEmpty(self) -> bool:
        return not any(
            [
                self.program,
                self.class_year,
                self.gender,
                self.city,
                self.country,
                self.country_expertise,
                self.company,
                self.role,
                self.university,
                self.industry_expertise,
                self.professional_expertise,
            ]
        )


@dataclass
class ParsedQuery:
    semantic_query: str
    filters: QueryFilters
    is_valid_search: bool = True


# --------------------------------------------------------------------------- #
# Adaptive prompt caching (see module docstring for the cost rationale)        #
# --------------------------------------------------------------------------- #
_QUERY_TIMES: deque[float] = deque()


def _ShouldCache1h() -> bool:
    """Record this query and report whether the rolling 60-min rate clears the
    threshold at which a 1-hour cache write pays for itself."""
    now = time.monotonic()
    _QUERY_TIMES.append(now)
    cutoff = now - 3600
    while _QUERY_TIMES and _QUERY_TIMES[0] < cutoff:
        _QUERY_TIMES.popleft()
    return len(_QUERY_TIMES) >= settings.PARSER_CACHE_HOURLY_THRESHOLD


_SYSTEM_BLOCK: dict[str, Any] = {"type": "text", "text": _SYSTEM_PROMPT}


def _BuildSystem(cache_1h: bool) -> list[dict[str, Any]]:
    if not cache_1h:
        return [_SYSTEM_BLOCK]
    return [{**_SYSTEM_BLOCK, "cache_control": {"type": "ephemeral", "ttl": "1h"}}]


# Deterministic obscenity / slur backstop — used ONLY when the LLM moderator is
# unavailable (the fallback path), so it stays small and HIGH-PRECISION: every
# stem is chosen so it cannot appear inside an innocent word (each was checked
# against common RU/EN vocabulary). Notably we use `бляд`/`блят` not bare `бля`
# (which hides in "корабля"/"рубля"); `гомик` shares no substring with "экономика";
# `ублюд` is not in "наблюдать"/"соблюдать"; `проститу` does not match
# "простите"/"простить"; `еблан` is safe where bare "ебан" would hit "хлебание";
# the EN stems are word-anchored so `\bcunt\b` won't fire inside "Scunthorpe" and
# `\bnigg(er|a)\b` won't fire inside "niggardly". This only catches the most
# egregious queries; the LLM is the real gate.
_BACKSTOP = re.compile(
    # --- RU mat / obscenity ---
    r"шлюх|бляд|блят|гондон|гандон|"
    r"хуй|хуя|хуё|хуи|пизд|залуп|"
    r"еблан|уёб|уеб|выеб|"
    r"мудак|мудил|долбоёб|долбоеб|"
    # --- RU slurs / degrading ---
    r"пидор|пидар|пидорас|пидарас|педик|педераст|педрил|гомик|"
    r"мраз|ублюд|дебил|придур|"
    # --- RU sexual solicitation ---
    r"проститу|шалав|"
    # --- EN obscenity / slurs / solicitation (word-anchored) ---
    r"fuck|\bcunts?\b|\bwhores?\b|\bsluts?\b|\bbitch(?:es)?\b|"
    r"\bfaggots?\b|\bnigg(?:er|a)s?\b|\bassholes?\b|"
    r"\bprostitutes?\b|\brapists?\b",
    re.IGNORECASE,
)


def _BackstopReject(text: str) -> bool:
    return bool(_BACKSTOP.search(text))


def _CanonList(values: Any, allowed: set[str]) -> list[str]:
    if not isinstance(values, list):
        return []
    out: list[str] = []
    for v in values:
        if isinstance(v, str) and v.casefold() in allowed and v not in out:
            out.append(v)
    return out


def _CleanStr(value: Any) -> str | None:
    if isinstance(value, str):
        v = value.strip()
        return v or None
    return None


def _ProgramCanon(value: str | None) -> str | None:
    """Snap a program name to the exact canonical feed spelling when it matches
    the controlled vocab (so `terms` on f_program hits); keep raw otherwise."""
    if not value:
        return None
    return _PROGRAM_SET.get(value.casefold(), value)


def _Coerce(data: dict[str, Any], raw_text: str) -> ParsedQuery:
    valid = data.get("is_valid_search")
    # Fail open: only an explicit `false` rejects (a missing/garbled flag must not
    # silently block legitimate searches).
    if valid is False:
        return ParsedQuery(
            semantic_query="",
            filters=QueryFilters(),
            is_valid_search=False,
        )

    filters_raw = data.get("filters") or {}
    # Normalize gender to the feed's `sex` vocabulary (MALE / FEMALE) so it
    # matches the indexed f_sex directly.
    gender_raw = _CleanStr(filters_raw.get("gender"))
    gender = (
        gender_raw.upper()
        if gender_raw and gender_raw.casefold() in {"male", "female"}
        else None
    )

    year = filters_raw.get("class_year")
    if not isinstance(year, int):
        year = None

    semantic = _CleanStr(data.get("semantic_query")) or ""
    filters = QueryFilters(
        program=_ProgramCanon(_CleanStr(filters_raw.get("program"))),
        class_year=year,
        gender=gender,
        city=_CleanStr(filters_raw.get("city")),
        country=_CleanStr(filters_raw.get("country")),
        country_expertise=_CanonList(
            filters_raw.get("country_expertise"), _COUNTRY_EXP_SET
        ),
        company=_CleanStr(filters_raw.get("company")),
        role=_CleanStr(filters_raw.get("role")),
        university=_CleanStr(filters_raw.get("university")),
        industry_expertise=_CanonList(
            filters_raw.get("industry_expertise"), _INDUSTRY_SET
        ),
        professional_expertise=_CanonList(
            filters_raw.get("professional_expertise"), _PROFESSIONAL_SET
        ),
    )
    # Guarantee retrieval always has *something* to match on.
    if not semantic and filters.IsEmpty():
        semantic = raw_text
    return ParsedQuery(
        semantic_query=semantic,
        filters=filters,
        is_valid_search=True,
    )


def _FirstText(response: Any) -> str:
    for block in response.content:
        if block.type == "text":
            return block.text
    return ""


async def ParseQuery(text: str) -> ParsedQuery:
    """Parse a search query into a moderation flag + semantic text + expansion +
    structured filters (fallback-safe)."""
    cache_1h = _ShouldCache1h()
    try:
        response = await client.with_options(
            timeout=settings.LLM_TIMEOUT_SECONDS
        ).messages.create(
            model=settings.QUERY_PARSER_MODEL,
            max_tokens=800,
            temperature=0,  # deterministic: one query → one parse (reproducible)
            system=_BuildSystem(cache_1h),
            messages=[{"role": "user", "content": text}],
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        )
        data = json.loads(_FirstText(response))
        parsed = _Coerce(data, raw_text=text)
        logging.info(
            "ParseQuery ok",
            extra={
                "query": text,
                "valid": parsed.is_valid_search,
                "semantic": parsed.semantic_query,
                "filters": parsed.filters,
            },
        )
        return parsed
    except Exception as exc:
        logging.warning(
            "ParseQuery failed; falling back to raw query.",
            extra={"query": text},
            exc_info=True,
        )
        await ReportLLMError(exc, "query-parser")
        if _BackstopReject(text):
            return ParsedQuery(
                semantic_query="",
                filters=QueryFilters(),
                is_valid_search=False,
            )
        return ParsedQuery(semantic_query=text, filters=QueryFilters())
