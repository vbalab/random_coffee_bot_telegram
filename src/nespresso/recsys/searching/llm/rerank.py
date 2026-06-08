"""
LLM reranker for Find search.

Takes the query plus the top-N hybrid-search candidates and asks a fast Haiku
call to reorder them best-first. **Compact mode**: the prompt numbers candidates
0..N-1 and the model returns just that list of indices reordered — no per-item
scores — which keeps output tokens (and therefore latency) low (~1.5s for 30).

Fallback-safe: any error / timeout / malformed response returns the input order
unchanged, so a flaky Claude API never breaks search. Any candidate the model
omits is appended in its original relative order.
"""

import json
import logging
from typing import Any

from nespresso.core.configs.settings import settings
from nespresso.recsys.searching.llm.client import client

_SYSTEM_PROMPT = """\
You are a precise reranker for a search over New Economic School (NES) alumni \
profiles. You are given a user query and a numbered list of candidate profiles \
already retrieved by hybrid search. Reorder ALL candidates from most to least \
relevant to the query's intent.

Judge relevance only on the information shown in each candidate — never invent \
facts. Weigh concrete matches (role, employer, skills/expertise, location, \
industry) over superficial keyword overlap. A candidate that clearly satisfies \
the query's specific constraints must rank above one that only loosely relates.

Return every candidate's number exactly once, ordered best-first. Output only the \
JSON object."""

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["ranking"],
    "properties": {
        "ranking": {"type": "array", "items": {"type": "integer"}},
    },
}

_SYSTEM = [
    {"type": "text", "text": _SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
]


def _FirstText(response: Any) -> str:
    for block in response.content:
        if block.type == "text":
            return block.text
    return ""


async def Rerank(query: str, candidates: list[tuple[int, str]]) -> list[int]:
    """
    Reorder `candidates` (list of (nes_id, profile_text)) best-first for `query`.
    Returns the reordered list of nes_ids. Identity fallback on any failure.
    """
    ids = [nes_id for nes_id, _ in candidates]
    if len(candidates) <= 1:
        return ids

    lines = "\n".join(f"[{i}] {text}" for i, (_, text) in enumerate(candidates))
    user = (
        f"Query: {query}\n\nCandidates:\n{lines}\n\n"
        f"Return all {len(candidates)} candidate numbers ordered best-first."
    )

    try:
        response = await client.with_options(
            timeout=settings.LLM_TIMEOUT_SECONDS
        ).messages.create(
            model=settings.RERANK_MODEL,
            max_tokens=600,
            temperature=0,  # deterministic ranking (reproducible, lower variance)
            system=_SYSTEM,
            messages=[{"role": "user", "content": user}],
            output_config={"format": {"type": "json_schema", "schema": _SCHEMA}},
        )
        order = json.loads(_FirstText(response)).get("ranking", [])
    except Exception:
        logging.warning(
            "Rerank failed; keeping hybrid order.",
            extra={"query": query, "n": len(candidates)},
            exc_info=True,
        )
        return ids

    seen: set[int] = set()
    out: list[int] = []
    for idx in order:
        if isinstance(idx, int) and 0 <= idx < len(ids) and idx not in seen:
            seen.add(idx)
            out.append(ids[idx])
    # Append anything the model dropped, preserving original order.
    for i, nes_id in enumerate(ids):
        if i not in seen:
            out.append(nes_id)
    return out
