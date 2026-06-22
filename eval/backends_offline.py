"""
Offline retrieval backends for the eval — runnable WITHOUT the OpenSearch/embedding
stack, so we can iterate on the parser/reranker quickly against the real profiles.

Important caveat: the `Lexical` baseline is a *proxy* for production. The real
baseline uses multilingual embeddings (GTE) that partially bridge EN↔RU, which
plain lexical matching cannot. So `Lexical` UNDERSTATES the production baseline,
and the parser/rerank lift measured here is an upper bound. The authoritative
numbers come from running the same dataset against real OpenSearch in Docker
(eval/backends_opensearch.py). These offline backends exist to validate the
dataset + harness and to demonstrate the new LLM components on real data.
"""

from __future__ import annotations

import math
import re
from collections import Counter

from eval.dataset import Profile, _edu, _n, city, company, grad_year, program
from nespresso.recsys.searching.llm.query_understanding import ParseQuery
from nespresso.recsys.searching.llm.rerank import Rerank

_TOKEN = re.compile(r"\w+", re.UNICODE)


def _tok(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.casefold()) if len(t) >= 2]


# Common university aliases → a distinctive substring of how the name is stored in
# the directory (abbreviations like "МГУ" never appear in the full official name).
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


def _uni_substrings(university: str) -> list[str]:
    """Match-substrings for a university filter (alias-expanded)."""
    u = _n(university)
    subs = {alias_val for alias_key, alias_val in _UNI_ALIASES.items() if alias_key in u}
    subs.add(u)  # also try the literal normalized form
    return [s for s in subs if s]


def ProfileBlob(r: Profile) -> str:
    parts: list[str] = [str(r.get("name") or "")]
    for f in ("city", "region", "country"):
        if r.get(f):
            parts.append(str(r[f]))
    for f in ("hobbies", "industry_expertise", "professional_expertise",
              "country_expertise"):
        parts += [str(x) for x in (r.get(f) or [])]
    works = []
    if isinstance(r.get("main_work"), dict):
        works.append(r["main_work"])
    works += [w for w in (r.get("additional_work") or []) if isinstance(w, dict)]
    for w in works:
        for k in ("company", "position", "industry", "department"):
            if w.get(k):
                parts.append(str(w[k]))
    for f in ("pre_nes_education", "post_nes_education"):
        for e in r.get(f) or []:
            if isinstance(e, dict):
                for k in ("university", "specialty", "specialization", "program"):
                    if e.get(k):
                        parts.append(str(e[k]))
    for p in r.get("programs") or []:
        if isinstance(p, dict):
            if p.get("name"):
                parts.append(str(p["name"]))
            if p.get("year"):
                parts.append(str(p["year"]))
    return " ".join(parts)


def ShortCandidate(r: Profile) -> str:
    """Compact one-line profile for the reranker prompt."""
    bits = [str(r.get("name") or "")]
    if r.get("city"):
        bits.append(str(r["city"]))
    mw = r.get("main_work")
    if isinstance(mw, dict):
        bits.append(" / ".join(str(mw[k]) for k in ("company", "position", "industry")
                               if mw.get(k)))
    progs = [
        str(p["name"]) for p in (r.get("programs") or [])
        if isinstance(p, dict) and p.get("name")
    ]
    if progs:
        bits.append("program: " + ", ".join(progs))
    petags = [str(x) for x in (r.get("professional_expertise") or []) if x]
    if petags:
        bits.append("expertise: " + ", ".join(petags[:6]))
    ietags = [str(x) for x in (r.get("industry_expertise") or []) if x]
    if ietags:
        bits.append("industry: " + ", ".join(ietags[:4]))
    return " | ".join(b for b in bits if b)


class _Corpus:
    """Shared lexical index over all profiles (idf + per-doc token sets)."""

    def __init__(self, profiles: list[Profile]):
        self.profiles = profiles
        self.docs: list[set[str]] = [set(_tok(ProfileBlob(r))) for r in profiles]
        self.edu_uni: list[str] = [
            " ".join(_n(e.get("university")) for e in _edu(r)) for r in profiles
        ]
        df: Counter[str] = Counter()
        for d in self.docs:
            df.update(d)
        n = len(profiles)
        self.idf = {t: math.log(1 + n / (1 + c)) for t, c in df.items()}

    def lexical(self, query_tokens: list[str], doc_idx: int) -> float:
        d = self.docs[doc_idx]
        return sum(self.idf.get(t, 0.0) for t in set(query_tokens) if t in d)


class Lexical:
    """Baseline proxy: BM25-lite over raw query."""

    name = "baseline(lexical)"

    def __init__(self, corpus: _Corpus):
        self.c = corpus

    async def rank(self, query: str) -> list[int]:
        qt = _tok(query)
        scored = [
            (self.c.lexical(qt, i), r["nes_id"])
            for i, r in enumerate(self.c.profiles)
        ]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [nid for s, nid in scored if s > 0] + [
            r["nes_id"] for i, r in enumerate(self.c.profiles)
            if self.c.lexical(qt, i) <= 0
        ][:0]  # keep only positives; zeros add no signal


class ParserFilter:
    """Parser → structured-field boosts + lexical on the cleaned semantic query."""

    name = "+parser+filters"

    def __init__(self, corpus: _Corpus):
        self.c = corpus

    async def rank(self, query: str) -> list[int]:
        parsed = await ParseQuery(query)
        f = parsed.filters
        sem_tokens = _tok(parsed.semantic_query)
        role_tokens = _tok(f.role or "")
        scored: list[tuple[float, int]] = []
        uni_subs = _uni_substrings(f.university) if f.university else []
        for i, r in enumerate(self.c.profiles):
            struct = 0.0
            if f.city and city(r, _n(f.city)):
                struct += 3
            if f.country and (_n(f.country) in _n(r.get("country"))):
                struct += 2
            struct += 2 * len(set(f.country_expertise)
                              & set(r.get("country_expertise") or []))
            if f.company and company(r, _n(f.company)):
                struct += 3
            struct += 2 * len(set(f.professional_expertise)
                              & set(r.get("professional_expertise") or []))
            struct += 2 * len(set(f.industry_expertise)
                              & set(r.get("industry_expertise") or []))
            if f.program and program(r, _n(f.program)):
                struct += 3
            if f.class_year and grad_year(r, f.class_year):
                struct += 2
            if f.gender and _n(f.gender) == _n(r.get("sex")):
                struct += 2
            if uni_subs and any(s in self.c.edu_uni[i] for s in uni_subs):
                struct += 3
            if role_tokens:
                struct += 0.5 * self.c.lexical(role_tokens, i)
            sem = self.c.lexical(sem_tokens, i)
            total = struct * 10 + sem
            if total > 0:
                scored.append((total, r["nes_id"]))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [nid for _, nid in scored]


class Reranked:
    """Wrap a base backend: take its top-N, Claude-rerank, splice back."""

    def __init__(self, base, corpus: _Corpus, n: int = 30):
        self.base = base
        self.c = corpus
        self.n = n
        self.name = f"{base.name}+rerank"
        self._by_id = {r["nes_id"]: r for r in corpus.profiles}

    async def rank(self, query: str) -> list[int]:
        base_order = await self.base.rank(query)
        head = base_order[: self.n]
        if len(head) <= 1:
            return base_order
        cands = [(nid, ShortCandidate(self._by_id[nid])) for nid in head]
        reranked = await Rerank(query, cands)
        return reranked + base_order[self.n :]
