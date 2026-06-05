"""
Run the Find-search eval and print a backend comparison.

    PYTHONPATH=src python -m eval.run            # offline backends (no OpenSearch)

Materializes eval/dataset.json, then scores each backend on every query with a
non-empty gold set. The `unsupported` query (program/year/gender) is shown
qualitatively only (its gold is empty by construction).
"""

from __future__ import annotations

import asyncio

from eval.backends_offline import Lexical, ParserFilter, Reranked, _Corpus
from eval.dataset import QUERIES, LoadProfiles, MaterializeGold, SaveDataset
from eval.metrics import KS, Mean, Score
from nespresso.recsys.searching.llm.query_understanding import ParseQuery


def _fmt(mean: dict) -> str:
    p = mean["precision"]
    r = mean["recall"]
    nd = mean["ndcg"]
    return (
        f"P@5={p[5]:.2f} P@10={p[10]:.2f} P@20={p[20]:.2f} | "
        f"R@10={r[10]:.2f} R@20={r[20]:.2f} | "
        f"MRR={mean['mrr']:.2f} nDCG@10={nd[10]:.2f}"
    )


async def main() -> None:
    print("Loading profiles + materializing gold...")
    profiles = LoadProfiles()
    gold = MaterializeGold(profiles)
    summary = SaveDataset()
    print(f"alumni={summary['total_alumni']}  queries={len(QUERIES)}  "
          f"(saved eval/dataset.json)\n")

    # ---- dataset summary + parser output per query ----
    print("=== DATASET + PARSER OUTPUT ===")
    for q in QUERIES:
        parsed = await ParseQuery(q.text)
        f = parsed.filters
        extracted = {
            k: v for k, v in {
                "program": f.program, "year": f.class_year, "gender": f.gender,
                "city": f.city, "country": f.country, "company": f.company,
                "role": f.role, "industry": f.industry_expertise,
                "prof": f.professional_expertise,
            }.items() if v
        }
        gr = len(gold[q.id]) / summary["total_alumni"]
        print(f"\n[{q.id}] {q.text!r}  gold={len(gold[q.id])} (rand P≈{gr:.2f})")
        print(f"   semantic={parsed.semantic_query!r}")
        print(f"   filters={extracted}")
        if q.note:
            print(f"   note: {q.note}")

    # ---- backend comparison ----
    corpus = _Corpus(profiles)
    base = Lexical(corpus)
    pf = ParserFilter(corpus)
    rr = Reranked(pf, corpus, n=30)
    backends = [base, pf, rr]

    scored_queries = [q for q in QUERIES if gold[q.id]]
    print(f"\n\n=== BACKEND COMPARISON ({len(scored_queries)} scored queries) ===")
    per_backend: dict[str, list] = {}
    for b in backends:
        scores = []
        for q in scored_queries:
            ranked = await b.rank(q.text)
            scores.append(Score(q.id, ranked, gold[q.id]))
        per_backend[b.name] = scores
        print(f"{b.name:28} {_fmt(Mean(scores))}")

    # ---- per-query nDCG@10 table ----
    print("\n=== per-query nDCG@10 ===")
    header = "query".ljust(14) + "".join(b.name[:16].rjust(18) for b in backends)
    print(header)
    by_qid = {b.name: {s.qid: s for s in per_backend[b.name]} for b in backends}
    for q in scored_queries:
        row = q.id.ljust(14)
        for b in backends:
            row += f"{by_qid[b.name][q.id].ndcg[10]:.2f}".rjust(18)
        print(row)


if __name__ == "__main__":
    asyncio.run(main())
