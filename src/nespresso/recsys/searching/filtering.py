"""
Structured boosting for Find search.

The parser (`query_understanding.ParseQuery`) turns a query into a cleaned
`semantic_query` plus structured `QueryFilters`. Hybrid OpenSearch retrieves a
candidate pool on the semantic query; this module then re-scores those candidates
by how well they match the structured filters — controlled-vocab expertise (exact),
location / company / university (substring), etc. — exactly mirroring the logic the
eval harness validated.

We deliberately re-score in Python over a retrieved pool (rather than hard-filter
in OpenSearch) so an over-eager filter can never zero out results — a missing match
just means no boost.

The flat `f_*` fields built by `StructuredFields()` are stored in the OpenSearch
document `_source` so the re-score needs no extra DB round-trip.
"""

from __future__ import annotations

from typing import Any

from nespresso.recsys.searching.llm.query_understanding import QueryFilters

# Weight applied to the structured boost relative to the (normalized, ~[0,1])
# hybrid score, so that — when filters are present — structured matches dominate
# ordering and the hybrid score breaks ties. With no filters, boost is 0 and the
# pure hybrid order stands.
STRUCT_WEIGHT = 10.0

# University abbreviations → a distinctive substring of the stored full name.
_UNI_ALIASES: dict[str, str] = {
    "мгу": "ломоносов", "msu": "ломоносов", "lomonosov": "ломоносов",
    "мфти": "физико-техническ", "физтех": "физико-техническ",
    "mipt": "физико-техническ", "phystech": "физико-техническ",
    "вшэ": "высшая школа экономики", "вышка": "высшая школа экономики",
    "hse": "высшая школа экономики",
    "нгу": "новосибирский государственный",
    "бауман": "баумана", "bauman": "баумана",
    "мифи": "мифи", "mephi": "мифи",
    "финуниверситет": "финансовый университет",
    "плеханов": "плеханова", "рэу": "плеханова",
    "спбгу": "санкт-петербургский государственный",
    "мгимо": "международных отношений", "mgimo": "международных отношений",
    "ранхигс": "народного хозяйства",
    "маи": "авиационный",
}


def _n(s: object) -> str:
    return " ".join(str(s or "").casefold().split())


def _uni_substrings(university: str) -> list[str]:
    u = _n(university)
    subs = {val for key, val in _UNI_ALIASES.items() if key in u}
    subs.add(u)
    return [s for s in subs if s]


def StructuredFields(nes_user: Any) -> dict[str, Any]:
    """Flatten a NesUser into the filterable fields stored in OpenSearch `_source`."""
    works = [nes_user.main_work] + (nes_user.additional_work or [])
    companies = [
        w["company"] for w in works
        if isinstance(w, dict) and w.get("company")
    ]
    edus = (nes_user.pre_nes_education or []) + (nes_user.post_nes_education or [])
    universities = [
        e["university"] for e in edus
        if isinstance(e, dict) and e.get("university")
    ]
    fields: dict[str, Any] = {
        "name": nes_user.name,
        "f_city": nes_user.city,
        "f_region": nes_user.region,
        "f_country": nes_user.country,
        "f_professional": nes_user.professional_expertise or [],
        "f_industry": nes_user.industry_expertise or [],
        "f_country_exp": nes_user.country_expertise or [],
        "f_company": " | ".join(companies),
        "f_universities": " | ".join(universities),
    }
    # program / class_name are absent from the directory feed; only write them when
    # present (e.g. captured via byEmail) so the hourly sync doesn't null them in
    # the index via doc_as_upsert.
    if nes_user.program:
        fields["f_program"] = nes_user.program
    if nes_user.class_name:
        fields["f_class"] = nes_user.class_name
    return fields


# The `_source` fields the search must return for re-scoring + rerank cards.
SOURCE_FIELDS = [
    "name", "f_city", "f_region", "f_country", "f_program", "f_class",
    "f_professional", "f_industry", "f_country_exp", "f_company", "f_universities",
]


def StructuredBoost(filters: QueryFilters, doc: dict[str, Any]) -> float:
    """Score how well an OpenSearch `_source` doc matches the structured filters."""
    boost = 0.0

    city = _n(doc.get("f_city")) + " " + _n(doc.get("f_region"))
    if filters.city and _n(filters.city) in city:
        boost += 3
    if filters.country and _n(filters.country) in _n(doc.get("f_country")):
        boost += 2

    boost += 2 * len(set(filters.country_expertise) & set(doc.get("f_country_exp") or []))
    boost += 2 * len(set(filters.professional_expertise)
                     & set(doc.get("f_professional") or []))
    boost += 2 * len(set(filters.industry_expertise) & set(doc.get("f_industry") or []))

    if filters.company and _n(filters.company) in _n(doc.get("f_company")):
        boost += 3

    if filters.university:
        unis = _n(doc.get("f_universities"))
        if any(sub in unis for sub in _uni_substrings(filters.university)):
            boost += 3

    return boost


def CandidateCard(doc: dict[str, Any]) -> str:
    """Compact one-line profile for the reranker prompt, built from `_source`."""
    bits: list[str] = [str(doc.get("name") or "")]
    if doc.get("f_city"):
        bits.append(str(doc["f_city"]))
    if doc.get("f_company"):
        bits.append(str(doc["f_company"]))
    prof = [str(x) for x in (doc.get("f_professional") or []) if x]
    if prof:
        bits.append("expertise: " + ", ".join(prof[:6]))
    ind = [str(x) for x in (doc.get("f_industry") or []) if x]
    if ind:
        bits.append("industry: " + ", ".join(ind[:4]))
    return " | ".join(b for b in bits if b)
