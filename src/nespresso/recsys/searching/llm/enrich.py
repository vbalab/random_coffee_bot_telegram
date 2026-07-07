"""
Index-time profile enrichment for Find search — INLINE contextual annotation.

Profiles describe themselves indirectly: someone employed at "XTX" / "Pinely"
never writes "high-frequency trading", so a query for "HFT" misses them. Neither
BM25 (no shared tokens) nor the small multilingual embedding reliably bridges
that gap — only world knowledge does.

The OLD approach appended a comma-separated KEYWORD BLOB to the profile text. It
helped BM25 but hurt the embedding: a detached bag of terms is out-of-distribution
for the (CLS-pooled, natural-language-trained) encoder and dilutes the single
profile vector.

This version keeps the world knowledge but changes its SHAPE. A fast Haiku call
rewrites the profile with short parenthetical glosses inserted IN PLACE, right
next to the entity each one explains — "Яндекс (крупная технологическая компания,
big tech, IT)", "ВШЭ, ФКН (strong CS school)". The result is ONE coherent
natural-language passage, in both Russian and English, that:
  - is embedding-friendly (glosses are grammatically attached to their entity,
    not a floating bag), and
  - still carries every world-knowledge token for exact BM25 matching,
so a single artifact now serves both retrieval channels well.

The annotation is ADDITIVE: the model is told to preserve every original word and
fact and only INSERT context. `_PreservesOriginal` verifies that (near-total
original-token retention); anything that fails validation — or any error/timeout —
falls back to the un-annotated text, so a flaky Claude API never breaks indexing.

The query side (`query_understanding.py`) expands queries against the SAME
`WORLD_KNOWLEDGE` taxonomy, so both ends of the match speak one vocabulary. (The
system prompt is below Haiku 4.5's 4096-token cache floor, so it is sent uncached
— caching here would be a silent no-op.)
"""

import asyncio
import logging
import re

from nespresso.core.configs.settings import settings
from nespresso.recsys.searching.llm.client import client
from nespresso.recsys.searching.llm.world_knowledge import WORLD_KNOWLEDGE

# Headroom for the whole annotated profile (original + inline glosses) so a long
# profile is never truncated mid-annotation (which would fail validation and
# waste the call).
_MAX_TOKENS = 2000

# The annotation is additive, so the enriched text must retain (near) all of the
# original's significant tokens. Below this we assume the model rewrote/dropped
# content and fall back to the raw text.
_MIN_TOKEN_RETENTION = 0.9

_SYSTEM_PROMPT = f"""\
You annotate a New Economic School (NES / РЭШ) alumni profile with brief \
world-knowledge context so it can be found by semantic search even when the \
searcher uses different words than the profile.

You are given the profile text. Return the SAME text, UNCHANGED, except that you \
INSERT a short parenthetical gloss immediately after the entities that benefit \
from context:
- after an EMPLOYER — its well-known name in the OTHER language if it differs, \
plus its industry / category. Examples: "Яндекс" -> "Яндекс (Yandex, крупная \
технологическая компания, big tech, IT)"; "Сбербанк" -> "Сбербанк (Sberbank, \
крупный российский банк / major Russian bank)". A name already written in Latin \
(e.g. "McKinsey", "XTX Markets") needs no transliteration.
- after a ROLE / position — the core skills or domain it implies, only if not \
already stated nearby. Example: "Quant Researcher" -> "Quant Researcher \
(алготрейдинг, статистика, машинное обучение / quantitative trading, statistics)".
- after a UNIVERSITY / faculty / program — its well-known name or abbreviation in \
the other language if it differs, plus its field or reputation. Example: "Высшая \
школа экономики, факультет компьютерных наук" -> "Высшая школа экономики (HSE), \
факультет компьютерных наук (сильная программа по computer science / strong CS \
school)".

Rules:
- PRESERVE every original word, line, number and fact verbatim — copy the \
original characters EXACTLY and never transliterate, re-spell, translate, \
reorder, remove or rewrite any existing text (keep Cyrillic letters Cyrillic). \
ONLY ADD parenthetical context, and never change a fact.
- Write each gloss in BOTH Russian and English and keep it SHORT (a few terms).
- Use only widely-known world knowledge. Do NOT invent personal facts (titles, \
employers, achievements, dates) that are not already in the text.
- Add a gloss only where it genuinely helps, and leave a line unchanged if it \
needs none. If the SAME named employer or school appears more than once, gloss \
ONLY its first occurrence and leave the later mentions exactly as they were.
- Output ONLY the annotated profile text, nothing else.

Reference knowledge (map named employers to their category; both languages):

{WORLD_KNOWLEDGE}

Example
Input:
Петров Пётр Петрович
Current position: Analyst at McKinsey
Professional expertise: стратегия, консалтинг
Post-NES education: МГУ, экономический факультет

Output:
Петров Пётр Петрович
Current position: Analyst at McKinsey (стратегический консалтинг, MBB / strategy \
consulting)
Professional expertise: стратегия, консалтинг
Post-NES education: МГУ, экономический факультет (МГУ им. Ломоносова / Lomonosov \
Moscow State University, top economics school)"""

_SYSTEM = [{"type": "text", "text": _SYSTEM_PROMPT}]

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _FirstText(response: object) -> str:
    return "".join(b.text for b in response.content if b.type == "text")  # type: ignore[attr-defined]


def _SignificantTokens(text: str) -> set[str]:
    """Case-folded word tokens of length >= 3 (drops punctuation and noise)."""
    return {t.casefold() for t in _TOKEN_RE.findall(text) if len(t) >= 3}


def _PreservesOriginal(original: str, enriched: str) -> bool:
    """
    True if the enriched text retains (near) all of the original's significant
    tokens — i.e. the model only ADDED context and did not rewrite or drop facts.
    Additive annotation makes the enriched text a near-superset of the original.
    """
    orig = _SignificantTokens(original)
    if not orig:
        return bool(enriched.strip())
    kept = orig & _SignificantTokens(enriched)
    return len(kept) / len(orig) >= _MIN_TOKEN_RETENTION


async def _EnrichOne(text: str, semaphore: asyncio.Semaphore) -> str:
    """Return the inline-annotated profile. Empty inputs and any failure or
    unfaithful (non-additive) output fall back to the original text."""
    if not text.strip():
        return text
    async with semaphore:
        try:
            response = await client.with_options(
                timeout=settings.ENRICH_TIMEOUT_SECONDS
            ).messages.create(
                model=settings.ENRICH_MODEL,
                max_tokens=_MAX_TOKENS,
                temperature=0,  # deterministic: reproducible index, easier to debug
                system=_SYSTEM,
                messages=[{"role": "user", "content": text}],
            )
            out = _FirstText(response).strip()
            if out and _PreservesOriginal(text, out):
                name = text.splitlines()[0] if text.splitlines() else ""
                logging.debug(f"enriched [{name}]: {out!r}")
                return out
            logging.warning(
                "Enrichment output unfaithful or empty; using raw text.",
                extra={
                    "first_line": text.splitlines()[0] if text.splitlines() else ""
                },
            )
            return text
        except Exception:
            logging.warning("Profile enrichment failed; using raw text.", exc_info=True)
            return text


async def EnrichTexts(texts: list[str]) -> list[str]:
    """
    Return each profile text with inline world-knowledge glosses added (aligned
    1:1 with input, fallback-safe). Bounded concurrency keeps us within API limits.
    """
    if not settings.ENRICH_ENABLED or not texts:
        return texts

    semaphore = asyncio.Semaphore(settings.ENRICH_CONCURRENCY)
    return await asyncio.gather(*(_EnrichOne(t, semaphore) for t in texts))
