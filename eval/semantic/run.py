"""
Semantic Find-search eval — the authoritative RETRIEVAL-QUALITY benchmark
(complements the predicate eval, which is really a parser/taxonomy regression test).

    PYTHONPATH=src python -m eval.semantic.run

Pipeline: for each query in queries.json -> pool candidates (pipeline+BM25+KNN) ->
LLM-judge each (query, profile) 0..3 by MEANING (cached) -> score the production
ranking with GRADED nDCG / MAP / recall. Writes:
  - labels.json     : {qid: {nes_id: grade}}   (the judged gold; reusable by ablate.py)
  - review.jsonl    : human spot-check rows (query, profile, grade, reason)

Run inside the bot container (needs OpenSearch + Postgres + model + CLAUDE_API_KEY).
"""

from __future__ import annotations

import asyncio
import collections
import json
import os
from pathlib import Path

from nespresso.db.models.nes_user import NesUser
from nespresso.db.services.user_context import GetUserContextService
from nespresso.recsys.searching.document import BuildProfileText

from eval.semantic.judge import JudgePool
from eval.semantic.metrics import Mean, Score
from eval.semantic.pool import PoolAndRank

_DIR = Path(__file__).parent
QUERIES_PATH = _DIR / "queries.json"
LABELS_PATH = _DIR / "labels.json"
REVIEW_PATH = _DIR / "review.jsonl"
_POOL_CONCURRENCY = 6


def _load_queries() -> list[dict]:
    data = json.loads(QUERIES_PATH.read_text())
    return data["queries"] if isinstance(data, dict) else data


async def main() -> None:
    queries = _load_queries()
    limit = int(os.environ.get("EVAL_LIMIT", "0"))  # smoke-test knob: first N queries
    if limit:
        queries = queries[:limit]
    # `family` groups the granular intents (semantic-* / structured-* / …) for the
    # per-intent report.
    intent = {q["id"]: q.get("family") or q.get("intent", "?").split("-")[0] for q in queries}
    ctx = await GetUserContextService()

    # 1. Pool + rank every query (bounded; each runs the real pipeline once).
    sem = asyncio.Semaphore(_POOL_CONCURRENCY)

    async def pool_one(q: dict) -> tuple[str, list[int], list[int]]:
        async with sem:
            ranking, pool = await PoolAndRank(q["text"])
        return q["id"], ranking, pool

    pooled = await asyncio.gather(*(pool_one(q) for q in queries))
    ranking_by_qid = {qid: r for qid, r, _ in pooled}
    pool_by_qid = {qid: p for qid, _, p in pooled}

    # 2. Build judge cards (the raw profile text: SearchText + bio) for every
    #    pooled profile, in one batched DB fetch.
    all_ids = sorted({nid for p in pool_by_qid.values() for nid in p})
    users = await ctx.GetNesUsersOnCondition(NesUser.nes_id.in_(all_ids)) or []
    abouts = await ctx.GetAboutByNesIds(all_ids)
    name_by_id = {u.nes_id: u.name for u in users}
    card_by_id = {u.nes_id: BuildProfileText(u, abouts.get(u.nes_id)) for u in users}
    cards_by_qid = {
        qid: [(nid, card_by_id[nid]) for nid in pool if nid in card_by_id]
        for qid, pool in pool_by_qid.items()
    }

    # 3. Judge (cached) -> graded labels.
    judged = await JudgePool(queries, cards_by_qid)
    labels_by_qid = {qid: {nid: v["grade"] for nid, v in d.items()} for qid, d in judged.items()}

    # 4. Score the production ranking against the graded labels.
    scores, by_intent = [], collections.defaultdict(list)
    print(f"\n{'qid':22} {'intent':11} rel  nDCG@10  R@10  P@5   {'query'}")
    for q in queries:
        qid = q["id"]
        s = Score(qid, ranking_by_qid.get(qid, []), labels_by_qid.get(qid, {}))
        scores.append(s)
        by_intent[intent[qid]].append(s)
        print(f"  {qid:20} {intent[qid]:11} {s.n_relevant:3}  "
              f"{s.ndcg[10]:.2f}    {s.recall[10]:.2f}  {s.precision[5]:.2f}  {q['text']!r}")

    m = Mean(scores)
    print(f"\n=== SEMANTIC EVAL ({m['n']} queries) ===")
    print("nDCG@5={:.3f} nDCG@10={:.3f} | R@10={:.3f} R@20={:.3f} | "
          "P@5={:.3f} | MAP={:.3f} MRR={:.3f}".format(
              m["ndcg"][5], m["ndcg"][10], m["recall"][10], m["recall"][20],
              m["precision"][5], m["map"], m["mrr"]))
    print("nDCG@10 by intent:  " + "   ".join(
        f"{k}={Mean(v)['ndcg'][10]:.3f}(n={len(v)})" for k, v in sorted(by_intent.items())))
    n_empty = sum(1 for s in scores if s.n_relevant == 0)
    if n_empty:
        print(f"note: {n_empty} queries had 0 judged-relevant profiles in pool "
              f"(retrieval miss or too-narrow intent) — excluded from recall mean.")

    # 5. Persist labels (gold for ablate.py) + a human spot-check file.
    LABELS_PATH.write_text(json.dumps(labels_by_qid, ensure_ascii=False, indent=1))
    with REVIEW_PATH.open("w") as f:
        for q in queries:
            qid = q["id"]
            rows = sorted(judged.get(qid, {}).items(), key=lambda kv: -kv[1]["grade"])
            for nid, v in rows:
                f.write(json.dumps({
                    "qid": qid, "query": q["text"], "intent": intent[qid],
                    "nes_id": nid, "name": name_by_id.get(nid, ""),
                    "grade": v["grade"], "reason": v.get("reason", ""),
                    "card": card_by_id.get(nid, "")[:240],
                }, ensure_ascii=False) + "\n")
    print(f"\nwrote {LABELS_PATH.name} + {REVIEW_PATH.name} (spot-check the 2s/3s).")


if __name__ == "__main__":
    asyncio.run(main())
