"""
Query understanding for Find search.

Parses a natural-language people-search query (Russian or English) into a cleaned
semantic query (for embedding + BM25) plus structured filters (for boosting /
filtering in OpenSearch). Runs a single fast Haiku call per search with the large
static domain prompt prompt-cached.

It is **fallback-safe**: any error, timeout, or malformed response degrades to
`ParsedQuery(semantic_query=<raw text>, filters=<empty>)` — i.e. exactly today's
behaviour — so a flaky Claude API never breaks search.

Forward-compatible: `program` / `class_year` / `gender` are extracted even though
the MyNES directory feed does not currently carry them — the moment that data
lands, the filters light up with zero code change.
"""

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from nespresso.core.configs.settings import settings
from nespresso.recsys.searching.llm.client import client

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


def _bullets(values: list[str]) -> str:
    return "\n".join(f"- {v}" for v in values)


_SYSTEM_PROMPT = f"""\
You convert a single natural-language people-search query into a structured search \
plan for an alumni network of the New Economic School (NES / Российская \
экономическая школа, РЭШ) in Moscow. Queries come from alumni looking for other \
alumni and are written in Russian, English, or a mix.

Return a JSON object with two parts:
1. `semantic_query` — a concise phrase capturing the descriptive *intent* of the \
search (roles, skills, topics), suitable for semantic / keyword matching against \
profile text. Strip filler and anything captured by a structured filter below. If \
the query is purely structured (e.g. only a program + year), set `semantic_query` \
to the most salient remaining descriptive terms (or an empty string if none).
2. `filters` — structured constraints extracted from the query. Use `null` (or an \
empty array) for anything not present. NEVER invent values that aren't implied by \
the query.

## Noise to drop
These appear in almost every query and carry no signal — never put them in \
`semantic_query` or any filter: выпускник, выпускники, выпускников, alumni, \
alum, РЭШ, NES, New Economic School, человек, людей, найди, найти, ищу, нужен, \
покажи, кто, find, search, looking for, someone, people, person.

## Filter fields
- `program`: NES study program if named. Canonical codes include МАЭ (Master of \
Arts in Economics / MAE), МФ (Master of Finance / MiF), MAF, MITE, MAPP. Map \
synonyms to the code (e.g. "магистратура по финансам" → "МФ", "MAE" → "МАЭ").
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
- `university`: a non-NES university if named, for pre/post-NES education. Use a \
recognizable short form (e.g. "МГУ", "МФТИ", "ВШЭ", "Физтех", "MIT") AND repeat it \
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

## Examples
Every filter key is always present (use null or [] when absent).

Query: "Выпускников мужчин программы МАЭ 2002"
{{"semantic_query": "", "filters": {{"program": "МАЭ", "class_year": 2002, \
"gender": "male", "city": null, "country": null, "country_expertise": [], \
"company": null, "role": null, "university": null, "industry_expertise": [], \
"professional_expertise": []}}}}

Query: "data scientists и ML инженеры в Москве"
{{"semantic_query": "data scientist machine learning engineer", "filters": \
{{"program": null, "class_year": null, "gender": null, "city": "Москва", \
"country": null, "country_expertise": [], "company": null, "role": "data \
scientist", "university": null, "industry_expertise": [], "professional_expertise": \
["Анализ данных", "Машинное обучение"]}}}}

Query: "founders of fintech startups in London"
{{"semantic_query": "fintech startup founder", "filters": {{"program": null, \
"class_year": null, "gender": null, "city": "Лондон", "country": null, \
"country_expertise": [], "company": null, "role": "founder", "university": null, \
"industry_expertise": ["IT, телеком"], "professional_expertise": ["Стартапы и \
инновации", "Предпринимательство"]}}}}

Query: "эксперты по рынку США в нефтегазе"
{{"semantic_query": "oil gas energy", "filters": {{"program": null, "class_year": \
null, "gender": null, "city": null, "country": null, "country_expertise": ["США"], \
"company": null, "role": null, "university": null, "industry_expertise": ["Нефть и \
газ"], "professional_expertise": []}}}}

Query: "выпускники МГУ"
{{"semantic_query": "МГУ Московский государственный университет", "filters": \
{{"program": null, "class_year": null, "gender": null, "city": null, "country": \
null, "country_expertise": [], "company": null, "role": null, "university": "МГУ", \
"industry_expertise": [], "professional_expertise": []}}}}

Query: "преподаватели и научные сотрудники"
{{"semantic_query": "teaching research academia professor", "filters": \
{{"program": null, "class_year": null, "gender": null, "city": null, "country": \
null, "country_expertise": [], "company": null, "role": "professor", "university": \
null, "industry_expertise": ["Образование"], "professional_expertise": \
["Преподавание"]}}}}

Output ONLY the JSON object."""

# Structured-output schema. No `enum` constraints (combining enum with a nullable
# type-array is rejected by the structured-outputs validator); allowed values are
# enforced via the prompt and validated in `_Coerce`.
_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["semantic_query", "filters"],
    "properties": {
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

_SYSTEM = [
    {
        "type": "text",
        "text": _SYSTEM_PROMPT,
        "cache_control": {"type": "ephemeral"},
    }
]


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


def _Coerce(data: dict[str, Any], raw_text: str) -> ParsedQuery:
    filters_raw = data.get("filters") or {}
    gender = _CleanStr(filters_raw.get("gender"))
    if gender is not None and gender.casefold() not in {"male", "female"}:
        gender = None

    year = filters_raw.get("class_year")
    if not isinstance(year, int):
        year = None

    semantic = _CleanStr(data.get("semantic_query")) or ""
    filters = QueryFilters(
        program=_CleanStr(filters_raw.get("program")),
        class_year=year,
        gender=gender.casefold() if gender else None,
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
    return ParsedQuery(semantic_query=semantic, filters=filters)


def _FirstText(response: Any) -> str:
    for block in response.content:
        if block.type == "text":
            return block.text
    return ""


async def ParseQuery(text: str) -> ParsedQuery:
    """Parse a search query into semantic text + structured filters (fallback-safe)."""
    try:
        response = await client.with_options(
            timeout=settings.LLM_TIMEOUT_SECONDS
        ).messages.create(
            model=settings.QUERY_PARSER_MODEL,
            max_tokens=400,
            system=_SYSTEM,
            messages=[{"role": "user", "content": text}],
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        )
        data = json.loads(_FirstText(response))
        parsed = _Coerce(data, raw_text=text)
        logging.info(
            "ParseQuery ok",
            extra={
                "query": text,
                "semantic": parsed.semantic_query,
                "filters": parsed.filters,
            },
        )
        return parsed
    except Exception:
        logging.warning(
            "ParseQuery failed; falling back to raw query.",
            extra={"query": text},
            exc_info=True,
        )
        return ParsedQuery(semantic_query=text, filters=QueryFilters())
