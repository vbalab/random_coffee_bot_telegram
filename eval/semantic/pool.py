"""
Candidate pooling for the semantic eval.

To judge relevance fairly we must judge a SUPERSET of what any config would
return, else a config is penalized for surfacing an unjudged (→ treated
irrelevant) profile. For each query we union:
  1. the full production pipeline's top ranks (parser + hybrid + structured + rerank),
  2. a raw-query BM25 lane (pure lexical),
  3. a raw-query KNN lane (pure semantic),
so the pool spans lexical, semantic, and fused/structured retrieval on the current
(enriched) index. (An enrichment-OFF ablation needs a second index + re-pool; see
ablate.py — do not read enrich-off scores off this pool.)
"""

from __future__ import annotations

import asyncio

from nespresso.recsys.searching.client import client
from nespresso.recsys.searching.index import INDEX_NAME
from nespresso.recsys.searching.preprocessing.embedding import CreateEmbedding
from nespresso.recsys.searching.preprocessing.model import RunInference
from nespresso.recsys.searching.search import ScrollingSearch

from eval.backends_opensearch import _fake_message

_LANE_K = 25  # per-lane depth pooled for judging


async def _pipeline_ids(query: str, k: int) -> list[int]:
    search = ScrollingSearch()
    await search.HybridSearch(_fake_message(query))  # type: ignore[arg-type]
    # _order_ids is the full fused+reranked ranking (materialized pages are only a
    # display chunk); fall back to it, else to the materialized pages.
    ids = getattr(search, "_order_ids", None) or [p.profile.nes_id for p in search.pages]
    return ids[:k]


async def _bm25_ids(query: str, k: int) -> list[int]:
    body = {"size": k, "_source": False, "query": {"match": {"text": query}}}
    resp = await client.search(index=INDEX_NAME, body=body)
    return [int(h["_id"]) for h in resp["hits"]["hits"]]


async def _knn_ids(query: str, k: int) -> list[int]:
    vec = await RunInference(CreateEmbedding, query)
    body = {
        "size": k,
        "_source": False,
        "query": {"knn": {"embedding": {"vector": vec, "k": k}}},
    }
    resp = await client.search(index=INDEX_NAME, body=body)
    return [int(h["_id"]) for h in resp["hits"]["hits"]]


async def PoolAndRank(query: str, lane_k: int = _LANE_K) -> tuple[list[int], list[int]]:
    """
    One pass per query: returns (pipeline_ranking, pool).
    - pipeline_ranking: the full production order (parser+hybrid+struct+rerank),
      top-30, used to SCORE the current pipeline.
    - pool: the dedup union of pipeline + BM25 + KNN lanes, JUDGED for relevance.
    Runs the pipeline only once (it costs Haiku parser+rerank calls).
    """
    lanes = await asyncio.gather(
        _pipeline_ids(query, max(lane_k, 30)),
        _bm25_ids(query, lane_k),
        _knn_ids(query, lane_k),
        return_exceptions=True,
    )
    pipeline = lanes[0] if not isinstance(lanes[0], Exception) else []
    seen: dict[int, None] = {}
    for lane in lanes:
        if isinstance(lane, Exception):
            continue
        for nid in lane[:lane_k]:
            seen.setdefault(nid, None)
    return pipeline[:30], list(seen)
