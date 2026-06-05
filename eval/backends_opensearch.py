"""
Production retrieval backend for the eval — drives the REAL Find pipeline
(`ScrollingSearch.HybridSearch`): parser → hybrid OpenSearch + structured pool →
re-score → Claude rerank.

Runs only where the full stack is available (the bot Docker image: OpenSearch +
Postgres + the embedding model + CLAUDE_API_KEY). This is the authoritative
measurement; the offline backends are a local proxy. Run via `eval/run_opensearch.py`.
"""

from __future__ import annotations

from types import SimpleNamespace

from nespresso.recsys.searching.search import ScrollingSearch


def _fake_message(text: str) -> SimpleNamespace:
    # HybridSearch only reads `.text` and `.chat.id`.
    return SimpleNamespace(text=text, chat=SimpleNamespace(id=0))


class OpenSearchBackend:
    name = "opensearch(production)"

    async def rank(self, query: str) -> list[int]:
        search = ScrollingSearch()
        await search.HybridSearch(_fake_message(query))  # type: ignore[arg-type]
        return [p.profile.nes_id for p in search.pages]
