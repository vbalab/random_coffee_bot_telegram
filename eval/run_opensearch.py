"""
Authoritative eval against the REAL production Find pipeline (OpenSearch + parser
+ rerank). Run inside the bot container, after a sync has populated the index:

    PYTHONPATH=src python -m eval.run_opensearch

Reports overall + per-category metrics on the same dataset as the offline run, so
the numbers are directly comparable (offline lexical baseline → production hybrid).
"""

from __future__ import annotations

import asyncio
import collections

from eval.backends_opensearch import OpenSearchBackend
from eval.dataset import QUERIES, LoadProfiles, MaterializeGold
from eval.metrics import KS, Mean, Score


async def main() -> None:
    profiles = LoadProfiles()
    gold = MaterializeGold(profiles)
    scored_queries = [q for q in QUERIES if gold[q.id]]
    qcat = {q.id: q.category for q in scored_queries}

    backend = OpenSearchBackend()

    # Run queries concurrently (bounded): each query is 2 sequential Haiku calls,
    # so serial is ~5 min. Temperature 0 → results are identical regardless of
    # ordering; the semaphore just caps concurrent load on Claude / the encoder.
    sem = asyncio.Semaphore(8)

    async def _run(q):
        async with sem:
            ranked = await backend.rank(q.text)
        return Score(q.id, ranked, gold[q.id])

    scores = list(await asyncio.gather(*(_run(q) for q in scored_queries)))
    for q, s in zip(scored_queries, scores):
        print(f"  [{q.id:16}] gold={s.gold:4} P@5={s.precision[5]:.2f} "
              f"nDCG@10={s.ndcg[10]:.2f}  {q.text!r}")

    m = Mean(scores)
    print(f"\n=== {backend.name} ({len(scored_queries)} queries) ===")
    print(
        "P@5={:.2f} P@10={:.2f} P@20={:.2f} | R@10={:.2f} R@20={:.2f} | "
        "MRR={:.2f} nDCG@10={:.2f}".format(
            m["precision"][5], m["precision"][10], m["precision"][20],
            m["recall"][10], m["recall"][20], m["mrr"], m["ndcg"][10],
        )
    )
    bycat = collections.defaultdict(list)
    for s in scores:
        bycat[qcat[s.qid]].append(s)
    print("nDCG@10 by category:",
          "  ".join(f"{c}={Mean(v)['ndcg'][10]:.2f}" for c, v in sorted(bycat.items())))


if __name__ == "__main__":
    asyncio.run(main())
