"""
Index-time profile enrichment for Find search.

Profiles describe themselves indirectly: someone employed at "XTX" / "Pinely"
never writes "high-frequency trading", so a query for "HFT" misses them. Neither
BM25 (no shared tokens) nor the small multilingual embedding reliably bridges
that — only world knowledge does.

Before embedding, each profile is run through a fast Haiku call that emits the
IMPLICIT professional context (employer industries, role-implied skills, domain
terms — in BOTH Russian and English). That text is APPENDED to the original
profile text, so:
  - the original tokens survive verbatim (exact BM25),
  - the embedding + BM25 now also carry the world-knowledge terms,
so "HFT" / "высокочастотный трейдинг" matches the XTX person.

The query side (`query_understanding.py`) expands queries against the SAME
`WORLD_KNOWLEDGE` taxonomy, so both ends of the match speak one vocabulary.

Fallback-safe: any per-profile failure leaves that profile's text unchanged.
(The system prompt is below Haiku 4.5's 4096-token cache floor, so it is sent
uncached — caching here would be a silent no-op.)
"""

import asyncio
import logging

from nespresso.core.configs.settings import settings
from nespresso.recsys.searching.llm.client import client
from nespresso.recsys.searching.llm.world_knowledge import WORLD_KNOWLEDGE

_SYSTEM_PROMPT = f"""\
You enrich a New Economic School (NES / РЭШ) alumni profile so it can be found by \
semantic search even when the searcher uses different words than the profile.

Given the profile text, output a SHORT block of ADDITIONAL context that makes the \
profile's implicit professional attributes explicit, using widely-known world \
knowledge. DO NOT repeat the profile verbatim and DO NOT invent personal facts \
(names, titles, achievements) that aren't implied. Output only the added terms / \
short phrases, comma-separated, **in both Russian and English**, so queries in \
either language match.

Add, where applicable:
- The INDUSTRY / CATEGORY of each named employer.
- The SKILLS / DOMAINS implied by the role and employer.
- Common synonyms and abbreviations for those concepts.

Reference knowledge (expand named employers to their category — both languages):

{WORLD_KNOWLEDGE}

Keep the output concise (one block of comma-separated terms, ~15-40 items). If \
the profile implies nothing notable, output an empty line."""

_SYSTEM = [{"type": "text", "text": _SYSTEM_PROMPT}]


def _FirstText(response: object) -> str:
    return "".join(b.text for b in response.content if b.type == "text")  # type: ignore[attr-defined]


async def _EnrichOne(text: str, semaphore: asyncio.Semaphore) -> str:
    """Return the world-knowledge additions for one profile ('' on failure/empty)."""
    if not text.strip():
        return ""
    async with semaphore:
        try:
            response = await client.with_options(
                timeout=settings.ENRICH_TIMEOUT_SECONDS
            ).messages.create(
                model=settings.ENRICH_MODEL,
                max_tokens=300,
                system=_SYSTEM,
                messages=[{"role": "user", "content": text}],
            )
            add = _FirstText(response).strip()
            if add:
                name = text.splitlines()[0] if text.splitlines() else ""
                logging.debug(f"enriched [{name}]: {add}")
            return add
        except Exception:
            logging.warning("Profile enrichment failed; using raw text.", exc_info=True)
            return ""


async def EnrichTexts(texts: list[str]) -> list[str]:
    """
    Append world-knowledge context to each profile text (aligned 1:1 with input,
    fallback-safe). Bounded concurrency keeps us within API limits.
    """
    if not settings.ENRICH_ENABLED or not texts:
        return texts

    semaphore = asyncio.Semaphore(settings.ENRICH_CONCURRENCY)
    additions = await asyncio.gather(*(_EnrichOne(t, semaphore) for t in texts))
    return [
        f"{text}\n\n{add}" if add else text
        for text, add in zip(texts, additions, strict=True)
    ]
