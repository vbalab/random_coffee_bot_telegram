# Semantic Find-search eval

The **retrieval-quality** benchmark. The older predicate eval (`eval/dataset.py`)
grades against structured MyNES fields — the same fields the structured lane
retrieves from — so it mostly measures the parser's query→enum mapping and is
*blind to* (and can even penalize) semantic/embedding/enrichment quality. This eval
fixes that: **subagents** judge **graded** relevance by *meaning*, so ranking,
recall, and semantic reach are actually measured. Keep both — the predicate eval is
a fine parser regression test.

## How it works

```
queries.json ─▶ pool (pipeline + BM25 + KNN) ─▶ SUBAGENT judge 0–3 (cached)
                                                        │
                          score production ranking ◀── labels.json (graded gold)
                          with graded nDCG / MAP / recall
```

- **Judge = subagents, not the paid API.** `judge.py` is CACHE-ONLY — it serves
  grades from `judgments.json` and cannot spend API money. New/unjudged pairs are
  written to `to_judge.json`; a **Workflow** (`judge_subagents.js`) grades them on
  the Claude Code plan and merges them back. So building/refreshing the gold costs
  **$0 of Anthropic API**.
- **Pool** unions the pipeline + raw BM25 + raw KNN lanes so the judged set is a
  superset of what any config surfaces.
- **Metrics** are graded (`2**rel − 1` gain) with a true recall denominator.

## ⚠️ What DOES touch the app's API

The **judge** never does. But `run.py` and `ablate.py` execute the **real Find
pipeline** to pool/score, and the pipeline calls its **Haiku** parser + reranker
via the app's `CLAUDE_API_KEY` — that *is* the thing being measured, so it's
unavoidable when scoring the live pipeline. It's cheap (Haiku, prompt-cached
parser), but it is the user's API. Do not run these without intending that.

## Run

```bash
# inside the bot container (OpenSearch + Postgres + model). Pool + score:
PYTHONPATH=src python -m eval.semantic.run       # serves cached gold; writes labels.json + review.jsonl
#   -> if it reports N unjudged pairs, it wrote to_judge.json. Grade them with subagents:
#         Workflow({ scriptPath: "eval/semantic/judge_subagents.js" })
#      then re-run the line above (now all served from cache).

# SPOT-CHECK the gold: open review.jsonl, sanity-check the 2s/3s.

# Compare configs against the SAME cached labels (no re-judging):
PYTHONPATH=src python -m eval.semantic.ablate
```

## Files

| File | Role |
|------|------|
| `queries.json` | ~76 curated, grounded, discriminative queries across 4 intents (semantic / structured / hobby_edu / name) |
| `pool.py` | candidate pooling (pipeline + BM25 + KNN) |
| `judge.py` | CACHE-ONLY judge — serves `judgments.json`, emits `to_judge.json`, never calls any API |
| `judge_subagents.js` | Workflow that grades `to_judge.json` via subagents → `judgments.json` |
| `metrics.py` | graded nDCG / precision / recall / MAP / MRR |
| `run.py` | orchestrator → `labels.json` (gold) + `review.jsonl` (spot-check) |
| `ablate.py` | score many pipeline configs against the cached labels |
| `judgments.json` | durable graded gold (query,profile → grade); reproducible, committed |

## Caveats

- **Enrichment on/off is not an ablate.py knob** — it changes the index, so it
  needs a second (raw) index + re-pool. Separate step.
- The gold is a strong first pass but not infallible — the spot-check step is what
  makes it trustworthy. `judgments.json` is the durable, reviewable record.
- ~76-query sample: treat sub-0.01 moves as noise.
