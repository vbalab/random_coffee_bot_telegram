"""
Graded-relevance ranking metrics for the semantic Find-search eval.

Unlike the predicate eval's binary gold (`eval/metrics.py`), relevance here is a
GRADED label per (query, profile) from an LLM judge:

    3 = ideal    2 = relevant    1 = marginal    0 = irrelevant

- nDCG@k uses the graded gain 2**rel - 1, so getting a `3` above a `2` matters
  (the predicate eval couldn't see this — all gold was equal).
- precision / recall / MAP / MRR use a binary cut at REL_THRESHOLD (>=2 = relevant),
  and recall's denominator is the number of relevant profiles IN THE JUDGED POOL
  (true recall over what was judged — the honest denominator, cf. the predicate
  eval which divided by min(gold,k) and so reported precision-as-recall).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

REL_THRESHOLD = 2  # rel >= this counts as "relevant" for binary metrics
KS = (5, 10, 20)


def _dcg(rels: list[int]) -> float:
    return sum((2**r - 1) / math.log2(i + 2) for i, r in enumerate(rels))


def _ndcg_at_k(ranked: list[int], labels: dict[int, int], k: int) -> float:
    gains = [labels.get(nid, 0) for nid in ranked[:k]]
    ideal = sorted(labels.values(), reverse=True)[:k]
    idcg = _dcg(ideal)
    return _dcg(gains) / idcg if idcg else 0.0


def _precision_at_k(ranked: list[int], relevant: set[int], k: int) -> float:
    if k == 0:
        return 0.0
    return sum(1 for nid in ranked[:k] if nid in relevant) / k


def _recall_at_k(ranked: list[int], relevant: set[int], k: int) -> float:
    if not relevant:
        return 0.0  # undefined; excluded from the mean by the caller
    return sum(1 for nid in ranked[:k] if nid in relevant) / len(relevant)


def _average_precision(ranked: list[int], relevant: set[int]) -> float:
    if not relevant:
        return 0.0
    hits = 0
    total = 0.0
    for i, nid in enumerate(ranked, start=1):
        if nid in relevant:
            hits += 1
            total += hits / i
    return total / len(relevant)


def _mrr(ranked: list[int], relevant: set[int]) -> float:
    for i, nid in enumerate(ranked, start=1):
        if nid in relevant:
            return 1.0 / i
    return 0.0


@dataclass
class QueryScore:
    qid: str
    n_relevant: int  # relevant profiles found in the judged pool
    ndcg: dict[int, float]
    precision: dict[int, float]
    recall: dict[int, float]
    ap: float
    mrr: float


def Score(qid: str, ranked: list[int], labels: dict[int, int]) -> QueryScore:
    """Score one query's ranked nes_id list against its graded `labels`."""
    relevant = {nid for nid, r in labels.items() if r >= REL_THRESHOLD}
    return QueryScore(
        qid=qid,
        n_relevant=len(relevant),
        ndcg={k: _ndcg_at_k(ranked, labels, k) for k in KS},
        precision={k: _precision_at_k(ranked, relevant, k) for k in KS},
        recall={k: _recall_at_k(ranked, relevant, k) for k in KS},
        ap=_average_precision(ranked, relevant),
        mrr=_mrr(ranked, relevant),
    )


def Mean(scores: list[QueryScore]) -> dict:
    """Aggregate. Recall is averaged only over queries that HAVE a relevant doc
    (an all-irrelevant query has undefined recall and would drag the mean to 0)."""
    n = len(scores) or 1
    with_rel = [s for s in scores if s.n_relevant > 0] or scores
    nr = len(with_rel)
    return {
        "n": len(scores),
        "ndcg": {k: sum(s.ndcg[k] for s in scores) / n for k in KS},
        "precision": {k: sum(s.precision[k] for s in scores) / n for k in KS},
        "recall": {k: sum(s.recall[k] for s in with_rel) / nr for k in KS},
        "map": sum(s.ap for s in scores) / n,
        "mrr": sum(s.mrr for s in scores) / n,
    }
