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

# How the structured signal joins the score. The hybrid `base` is already the
# min-max-normalized (0..1) fusion of the BM25 and KNN lanes. The raw
# StructuredBoost (a sum of +2/+3 per matched filter) is min-max-normalized THE
# SAME WAY across the candidate pool, so structured is just a third [0,1] signal —
# a peer of the semantic lanes, not a step that dwarfs them:
#
#     final = base + STRUCT_WEIGHT * boost_norm
#
# STRUCT_WEIGHT=1.0 gives the structured lane the SAME ceiling as the hybrid base
# (1.0), so a filter match is a true PEER of the semantic signal — it can never
# categorically override a strongly-relevant BM25/KNN candidate. The weight alone
# cannot fully prevent flooding (a high-frequency filter lifts ALL its matchers
# together, so >N of them still fill a top-N-by-score window); that is solved
# structurally by RESERVING rerank slots for pure-semantic candidates (see
# _RERANK_SEMANTIC_SLOTS in search.py), which is what actually guarantees relevant
# profiles reach the reranker. No filters -> boost 0 -> pure hybrid order stands.
STRUCT_WEIGHT = 1.0

def _n(s: object) -> str:
    return " ".join(str(s or "").casefold().split())


def StructuredFields(nes_user: Any) -> dict[str, Any]:
    """Flatten a NesUser into the filterable fields stored in OpenSearch `_source`."""
    works = [nes_user.main_work] + (nes_user.additional_work or [])
    companies = [
        w["company"] for w in works
        if isinstance(w, dict) and w.get("company")
    ]
    positions = [
        w["position"] for w in works
        if isinstance(w, dict) and w.get("position")
    ]
    edus = (nes_user.pre_nes_education or []) + (nes_user.post_nes_education or [])
    universities = [
        e["university"] for e in edus
        if isinstance(e, dict) and e.get("university")
    ]
    programs = nes_user.programs or []
    program_names = [
        p["name"] for p in programs if isinstance(p, dict) and p.get("name")
    ]
    class_years = [
        str(p["year"]) for p in programs if isinstance(p, dict) and p.get("year")
    ]
    fields: dict[str, Any] = {
        "name": nes_user.name,
        "f_sex": nes_user.sex or "",
        "f_city": nes_user.city,
        "f_region": nes_user.region,
        "f_country": nes_user.country,
        # Multi-valued (a person can have >1 program). Defensive null-drop on the
        # controlled-vocab arrays — the feed occasionally ships stray nulls.
        "f_program": program_names,
        "f_class_year": class_years,
        "f_professional": [v for v in (nes_user.professional_expertise or []) if v],
        "f_industry": [v for v in (nes_user.industry_expertise or []) if v],
        "f_country_exp": [v for v in (nes_user.country_expertise or []) if v],
        "f_company": " | ".join(companies),
        "f_universities": " | ".join(universities),
        # Job titles across all work records (current + prior). This is what the
        # parser's `role` filter matches against — the ground truth for role
        # searches ("data scientist", "консультант") is literally the position.
        "f_role": " | ".join(positions),
    }
    return fields


# The `_source` fields the search must return for re-scoring + rerank cards.
SOURCE_FIELDS = [
    "name", "f_sex", "f_city", "f_region", "f_country", "f_program", "f_class_year",
    "f_professional", "f_industry", "f_country_exp", "f_company", "f_universities",
    "f_role",
]


def RoleIsDominant(filters: QueryFilters) -> bool:
    """
    True when `role` is the primary intent — i.e. no other narrowing filter is
    present. On compound queries (role + company / industry / city / …) those
    filters define the answer, and letting `f_role` add recall + boost would flood
    the pool with title-only matches that bury the intended constraint. So f_role
    contributes ONLY when role stands alone.
    """
    return bool(filters.role) and not (
        filters.company
        or filters.university
        or filters.industry_expertise
        or filters.country_expertise
        or filters.city
        or filters.program
        or filters.class_year
    )


def StructuredBoost(filters: QueryFilters, doc: dict[str, Any]) -> float:
    """Score how well an OpenSearch `_source` doc matches the structured filters."""
    boost = 0.0

    city = _n(doc.get("f_city")) + " " + _n(doc.get("f_region"))
    if filters.city and _n(filters.city) in city:
        boost += 3
    if filters.country and _n(filters.country) in _n(doc.get("f_country")):
        boost += 2

    # gender is normalized to the feed's MALE/FEMALE in the parser (_Coerce).
    if filters.gender and filters.gender == doc.get("f_sex"):
        boost += 2
    if filters.program and filters.program in set(doc.get("f_program") or []):
        boost += 3
    if filters.class_year and str(filters.class_year) in set(
        doc.get("f_class_year") or []
    ):
        boost += 2

    boost += 2 * len(set(filters.country_expertise) & set(doc.get("f_country_exp") or []))
    boost += 2 * len(set(filters.professional_expertise)
                     & set(doc.get("f_professional") or []))
    boost += 2 * len(set(filters.industry_expertise) & set(doc.get("f_industry") or []))

    if filters.company and _n(filters.company) in _n(doc.get("f_company")):
        boost += 3

    # role ↔ position: the parser emits `role` bilingually + comma-separated
    # ("product manager, продакт-менеджер"); boost if any variant appears in the
    # person's job titles. Phrase-level (not token) so "product" alone doesn't
    # match "product owner". Gated on RoleIsDominant so it doesn't outweigh the
    # real constraint on compound queries.
    if RoleIsDominant(filters):
        f_role = _n(doc.get("f_role"))
        variants = [v for v in (_n(x) for x in filters.role.split(",")) if v]
        if any(v in f_role for v in variants):
            boost += 3

    # NOTE: no `university` term. University matching is handled the same way as
    # employers — via the index-time enrichment glossing (МГУ / MSU / Ломоносова,
    # Bocconi / Боккони, …) which feeds BM25 + embedding recall, and the reranker
    # (which sees "studied: <f_universities>" in the card) for precision. The old
    # hand-coded _UNI_ALIASES table was a redundant, buggy second copy of the
    # university knowledge that already lives in DIRECTORY_KNOWLEDGE.

    return boost


def CandidateCard(doc: dict[str, Any]) -> str:
    """Compact one-line profile for the reranker prompt, built from `_source`."""
    bits: list[str] = [str(doc.get("name") or "")]
    if doc.get("f_city"):
        bits.append(str(doc["f_city"]))
    prog = [str(x) for x in (doc.get("f_program") or []) if x]
    if prog:
        bits.append("program: " + ", ".join(prog))
    # Label work vs studied explicitly: the same name (e.g. "Боккони") can be an
    # employer or an alma mater, and the reranker must tell "works at X" from
    # "studied at X" (without the education line it ranked a Bocconi EMPLOYEE top
    # for "PhD from Bocconi").
    if doc.get("f_company"):
        bits.append("work: " + str(doc["f_company"]))
    if doc.get("f_universities"):
        bits.append("studied: " + str(doc["f_universities"]))
    prof = [str(x) for x in (doc.get("f_professional") or []) if x]
    if prof:
        bits.append("expertise: " + ", ".join(prof[:6]))
    ind = [str(x) for x in (doc.get("f_industry") or []) if x]
    if ind:
        bits.append("industry: " + ", ".join(ind[:4]))
    return " | ".join(b for b in bits if b)
