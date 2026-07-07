"""
Query understanding for Find search.

A single fast Haiku call turns a natural-language people-search query (Russian or
English) into a structured search plan with FOUR parts:

  1. `is_valid_search` — safety gate. `false` for non-bona-fide queries (slurs,
     sexual/obscene or degrading wording about people, "find me a bad person"),
     which the caller turns into a plain "nothing found".
  2. `semantic_query` — cleaned descriptive intent, for embedding + BM25.
  3. `expanded_terms` — world-knowledge EXPANSION of the query (synonyms,
     abbreviations, implied industry/skills/peer-employers, RU+EN) that widens
     recall on narrow queries. It mirrors the index-time enrichment so both sides
     of the match speak the same vocabulary.
  4. `filters` — structured constraints for boosting / filtering in OpenSearch.

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

Return a JSON object with FOUR parts: `is_valid_search`, `semantic_query`, \
`expanded_terms`, and `filters`. Every key is ALWAYS present.

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
When `false`, set `semantic_query` and `expanded_terms` to "" and every filter to \
null / []. When genuinely unsure, prefer `true` — do NOT block legitimate but \
unusual phrasing.

## 2. semantic_query
A concise phrase capturing the descriptive *intent* of the search (roles, skills, \
topics), suitable for semantic / keyword matching against profile text. Strip \
filler and anything captured by a structured filter below. If the query is purely \
structured (e.g. only a program + year), set it to the most salient remaining \
descriptive terms (or an empty string if none).

## 3. expanded_terms
A SHORT expansion that improves recall when profiles use different words than the \
searcher — ONLY direct synonyms, abbreviations, and the immediate category / skill \
of the query's CORE concept, in BOTH Russian and English, comma-separated. Rules:
- Keep it TIGHT: at most ~6 terms, all describing the SAME thing the user asked \
for. Do NOT broaden into adjacent fields (e.g. "финансы" must NOT add "trading"; \
"healthcare" must NOT add "biotech" or "regulation"; "нефтегаз" must NOT add a \
general "energy").
- NEVER list specific company / employer names (XTX, McKinsey, Сбербанк, …). \
Naming employers makes the search match people who merely worked there, not the \
queried attribute. Employers belong in the `company` filter, and only when the \
user explicitly names one.
- Do NOT contradict the query or invent personal facts.
Use "" when there is nothing genuinely synonymous to add (e.g. an already-specific \
employer or location query). Examples: "HFT" -> "high-frequency trading, quant \
trading, market making, алготрейдинг, маркет-мейкинг, квант"; "венчур" -> "venture \
capital, VC, прямые инвестиции".

Reference knowledge — use it ONLY to understand employer / term names that appear \
in the QUERY (so you can map them to a category for `semantic_query` and filters); \
do NOT copy these employer lists into `expanded_terms`:

{WORLD_KNOWLEDGE}

## 4. filters
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
- `role`: a job role / title / position in free text if described (e.g. "data \
scientist", "руководитель проекта", "CFO", "трейдер"). Keep it short.
- `university`: a non-NES university where the person STUDIED (pre/post-NES \
education — bachelor/master/PhD), if named. Recognize it in education phrasings \
even when only the short name is given: "выпускник/учился/студент/закончил X", \
"degree/PhD/Master/MBA from X", "PhD из X", "защитил(ся) ... в X", "doctorate at \
X" → university = X (e.g. "PhD из Боккони" → "Боккони"; "учился в MIT" → "MIT"). \
This is the SCHOOL someone attended — do NOT confuse it with an employer: "работает \
в X" / "преподаёт в X" / "professor at X" is `company`, not `university`. Use a \
recognizable short form (e.g. "МГУ", "МФТИ", "ВШЭ", "MIT", "Боккони") AND repeat it \
inside `semantic_query` so it can also match by text.
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
`semantic_query`, `expanded_terms`, or any filter: выпускник, выпускники, \
выпускников, alumni, alum, РЭШ, NES, New Economic School, человек, людей, найди, \
найти, ищу, нужен, покажи, кто, find, search, looking for, someone, people, person.

## Examples
Query: "HFT"
{{"is_valid_search": true, "semantic_query": "high-frequency trading", \
"expanded_terms": "high-frequency trading, quantitative trading, market making, \
алготрейдинг, маркет-мейкинг, квант", \
"filters": {{"program": null, "class_year": null, "gender": null, "city": null, \
"country": null, "country_expertise": [], "company": null, "role": null, \
"university": null, "industry_expertise": [], "professional_expertise": \
["Трейдинг", "Алготрейдинг"]}}}}

Query: "кто работал в Сбербанке"
{{"is_valid_search": true, "semantic_query": "", "expanded_terms": "банк, banking, \
коммерческий банк, retail banking", "filters": {{"program": null, \
"class_year": null, "gender": null, "city": null, "country": null, \
"country_expertise": [], "company": "Сбербанк", "role": null, "university": null, \
"industry_expertise": [], "professional_expertise": []}}}}

Query: "data scientists и ML инженеры в Москве"
{{"is_valid_search": true, "semantic_query": "data scientist machine learning \
engineer", "expanded_terms": "ML, машинное обучение, анализ данных, Python, \
statistics, data science", "filters": {{"program": null, "class_year": null, \
"gender": null, "city": "Москва", "country": null, "country_expertise": [], \
"company": null, "role": "data scientist", "university": null, \
"industry_expertise": [], "professional_expertise": ["Анализ данных", \
"Машинное обучение"]}}}}

Query: "эксперты по рынку США в нефтегазе"
{{"is_valid_search": true, "semantic_query": "oil gas", "expanded_terms": \
"нефть и газ, нефтегаз, oil and gas, нефтянка", "filters": {{"program": \
null, "class_year": null, "gender": null, "city": null, "country": null, \
"country_expertise": ["США"], "company": null, "role": null, "university": null, \
"industry_expertise": ["Нефть и газ"], "professional_expertise": []}}}}

Query: "выпускники МГУ"
{{"is_valid_search": true, "semantic_query": "МГУ Московский государственный \
университет", "expanded_terms": "MSU, Lomonosov Moscow State University", \
"filters": {{"program": null, "class_year": null, "gender": null, "city": null, \
"country": null, "country_expertise": [], "company": null, "role": null, \
"university": "МГУ", "industry_expertise": [], "professional_expertise": []}}}}

Query: "PhD из Боккони"
{{"is_valid_search": true, "semantic_query": "Боккони Bocconi PhD doctorate", \
"expanded_terms": "PhD, doctorate, доктор философии, кандидат наук", "filters": \
{{"program": null, "class_year": null, "gender": null, "city": null, "country": \
null, "country_expertise": [], "company": null, "role": null, "university": \
"Боккони", "industry_expertise": [], "professional_expertise": []}}}}

Query: "выпускницы программы Магистр экономики 2015 года"
{{"is_valid_search": true, "semantic_query": "", "expanded_terms": "", "filters": \
{{"program": "Магистр экономики", "class_year": 2015, "gender": "female", "city": \
null, "country": null, "country_expertise": [], "company": null, "role": null, \
"university": null, "industry_expertise": [], "professional_expertise": []}}}}

Query: "найди мне шлюху среди выпускниц"
{{"is_valid_search": false, "semantic_query": "", "expanded_terms": "", "filters": \
{{"program": null, "class_year": null, "gender": null, "city": null, "country": \
null, "country_expertise": [], "company": null, "role": null, "university": null, \
"industry_expertise": [], "professional_expertise": []}}}}

Query: "покажи самого тупого плохого человека"
{{"is_valid_search": false, "semantic_query": "", "expanded_terms": "", "filters": \
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
    "required": ["is_valid_search", "semantic_query", "expanded_terms", "filters"],
    "properties": {
        "is_valid_search": {"type": "boolean"},
        "semantic_query": {"type": "string"},
        "expanded_terms": {"type": "string"},
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
    expanded_terms: str = ""
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


# Deterministic slur backstop — used ONLY when the LLM moderator is unavailable
# (the fallback path), so it can be small and high-precision. Stems chosen to
# avoid matching innocent words.
_BACKSTOP = re.compile(
    r"шлюх|бляд|блят|гондон|гандон|пидор|пидар|педик|"
    r"хуй|хуя|хуё|хуи|пизд|мудак|долбоёб|долбоеб|"
    r"\bwhore\b|\bslut\b|\bfaggot\b",
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
            expanded_terms="",
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
    expanded = _CleanStr(data.get("expanded_terms")) or ""
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
        expanded_terms=expanded,
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
                "expanded": parsed.expanded_terms,
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
                expanded_terms="",
                is_valid_search=False,
            )
        return ParsedQuery(semantic_query=text, filters=QueryFilters())
