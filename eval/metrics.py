"""Ranking metrics for the Find-search eval (binary relevance)."""

from __future__ import annotations

import math
from dataclasses import dataclass

KS = (5, 10, 20)


@dataclass
class QueryScore:
    qid: str
    gold: int
    precision: dict[int, float]
    recall: dict[int, float]
    mrr: float
    ndcg: dict[int, float]


def _precision_at_k(ranked: list[int], gold: set[int], k: int) -> float:
    if k == 0:
        return 0.0
    top = ranked[:k]
    hits = sum(1 for x in top if x in gold)
    return hits / k


def _recall_at_k(ranked: list[int], gold: set[int], k: int) -> float:
    if not gold:
        return 0.0
    hits = sum(1 for x in ranked[:k] if x in gold)
    return hits / min(len(gold), k) if gold else 0.0


def _mrr(ranked: list[int], gold: set[int]) -> float:
    for i, x in enumerate(ranked, start=1):
        if x in gold:
            return 1.0 / i
    return 0.0


def _ndcg_at_k(ranked: list[int], gold: set[int], k: int) -> float:
    dcg = sum(1.0 / math.log2(i + 1) for i, x in enumerate(ranked[:k], start=1) if x in gold)
    ideal_hits = min(len(gold), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def Score(qid: str, ranked: list[int], gold: set[int]) -> QueryScore:
    return QueryScore(
        qid=qid,
        gold=len(gold),
        precision={k: _precision_at_k(ranked, gold, k) for k in KS},
        recall={k: _recall_at_k(ranked, gold, k) for k in KS},
        mrr=_mrr(ranked, gold),
        ndcg={k: _ndcg_at_k(ranked, gold, k) for k in KS},
    )


def Mean(scores: list[QueryScore]) -> dict:
    if not scores:
        return {}
    n = len(scores)
    return {
        "precision": {k: sum(s.precision[k] for s in scores) / n for k in KS},
        "recall": {k: sum(s.recall[k] for s in scores) / n for k in KS},
        "mrr": sum(s.mrr for s in scores) / n,
        "ndcg": {k: sum(s.ndcg[k] for s in scores) / n for k in KS},
    }
