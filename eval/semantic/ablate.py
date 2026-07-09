"""
Ablation runner: score many pipeline CONFIGS against the SAME judged labels.

The labels (eval/semantic/labels.json, from run.py) are query->doc relevance and
are config-INDEPENDENT, so once judged we can compare any number of retrieval
configs for FREE (no new judge calls). This is what the predicate eval could never
do: e.g. actually measure whether the reserved-semantic window, STRUCT_WEIGHT, the
KeyBERT lane, or the reranker help on graded semantic relevance.

    PYTHONPATH=src python -m eval.semantic.ablate

Config knobs are monkeypatched in the `search` module namespace (where the
constants are actually read). Enrichment on/off is NOT here — it needs a second
(raw) index; that ablation is a separate step.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from nespresso.core.configs.settings import settings
from nespresso.recsys.searching import search as S

from eval.semantic.metrics import Mean, Score
from eval.semantic.pool import _pipeline_ids

_DIR = Path(__file__).parent

# Each config: display name -> {attribute path -> value}. "S.x" patches the search
# module; "settings.x" patches the settings object. Missing keys keep the default.
CONFIGS: list[tuple[str, dict]] = [
    ("current (SW=1.0, window 25+5)", {}),
    ("SW=0.0 (filters off in re-score)", {"S.STRUCT_WEIGHT": 0.0}),
    ("SW=1.5", {"S.STRUCT_WEIGHT": 1.5}),
    ("SW=10 (old flat-ish)", {"S.STRUCT_WEIGHT": 10.0}),
    ("no reserved window (0 slots)", {"S._RERANK_SEMANTIC_SLOTS": 0}),
    ("reserved window 10 slots", {"S._RERANK_SEMANTIC_SLOTS": 10}),
    ("no reranker", {"settings.RERANK_ENABLED": False}),
    ("KNN k=100 (was 30)", {"S._KNN_LIMIT": 100}),
    ("no KeyBERT lane", {"S.ExtractKeywords": lambda _t: ""}),
]


def _apply(overrides: dict) -> dict:
    saved = {}
    for path, value in overrides.items():
        ns, attr = path.split(".", 1)
        obj = S if ns == "S" else settings
        saved[path] = getattr(obj, attr)
        setattr(obj, attr, value)
    return saved


def _restore(saved: dict) -> None:
    for path, value in saved.items():
        ns, attr = path.split(".", 1)
        obj = S if ns == "S" else settings
        setattr(obj, attr, value)


async def _score_config(queries: list[dict], labels: dict, conc: int = 6) -> dict:
    sem = asyncio.Semaphore(conc)

    async def one(q: dict):
        async with sem:
            ranking = await _pipeline_ids(q["text"], 30)
        return Score(q["id"], ranking, {int(k): v for k, v in labels.get(q["id"], {}).items()})

    scores = await asyncio.gather(*(one(q) for q in queries))
    return Mean(list(scores))


async def main() -> None:
    queries = json.loads((_DIR / "queries.json").read_text())
    queries = queries["queries"] if isinstance(queries, dict) else queries
    labels = json.loads((_DIR / "labels.json").read_text())

    print(f"{'config':34} nDCG@10  nDCG@5  R@10   MAP    MRR")
    base = None
    for name, overrides in CONFIGS:
        saved = _apply(overrides)
        try:
            m = await _score_config(queries, labels)
        finally:
            _restore(saved)
        d = m["ndcg"][10] - base if base is not None else 0.0
        base = base if base is not None else m["ndcg"][10]
        delta = "" if not overrides else f"  ({d:+.3f})"
        print(f"  {name:32} {m['ndcg'][10]:.3f}    {m['ndcg'][5]:.3f}   "
              f"{m['recall'][10]:.3f}  {m['map']:.3f}  {m['mrr']:.3f}{delta}")


if __name__ == "__main__":
    asyncio.run(main())
