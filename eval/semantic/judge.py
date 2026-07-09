"""
Relevance judge — CACHE-ONLY. Grades are produced by SUBAGENTS (a Workflow run by
the operator on the Claude Code plan), NEVER by a paid Anthropic-API call from this
process. This module imports no LLM client and cannot spend API money.

Flow:
  1. run.py builds (query, profile) pairs and calls JudgePool.
  2. JudgePool serves any pair already in `judgments.json` (the durable gold).
  3. Any UNjudged pair is written to `to_judge.json`; the operator then runs the
     subagent judge (`judge_subagents.js`, see README) which grades those pairs and
     merges the results back into `judgments.json`. Re-running run.py then serves
     them from cache.
Uncached pairs are treated as grade 0 for the current run (and reported), so a
partial gold never silently poisons — it just under-credits until judged.
"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

_DIR = Path(__file__).parent
_CACHE_PATH = _DIR / "judgments.json"
_PENDING_PATH = _DIR / "to_judge.json"


def _key(query: str, nes_id: int, card: str) -> str:
    h = hashlib.sha256(f"{query}\x00{nes_id}\x00{card}".encode()).hexdigest()[:16]
    return f"{nes_id}:{h}"


def _load_cache() -> dict[str, dict]:
    if _CACHE_PATH.is_file():
        try:
            return json.loads(_CACHE_PATH.read_text())
        except Exception:
            logging.warning("Could not read judge cache; starting empty.")
    return {}


async def JudgePool(
    queries: list[dict],
    cards_by_qid: dict[str, list[tuple[int, str]]],
) -> dict[str, dict[int, dict]]:
    """
    Serve graded labels from the cache. Returns {qid: {nes_id: {"grade","reason"}}}.
    Writes every uncached (query, profile) pair to `to_judge.json` for the subagent
    judge; NEVER calls any API.
    """
    cache = _load_cache()
    labels: dict[str, dict[int, dict]] = {}
    pending: list[dict] = []
    for q in queries:
        qid, text = q["id"], q["text"]
        d: dict[int, dict] = {}
        for nes_id, card in cards_by_qid.get(qid, []):
            hit = cache.get(_key(text, nes_id, card))
            if hit is not None:
                d[nes_id] = hit
            else:
                pending.append({
                    "key": _key(text, nes_id, card),
                    "qid": qid,
                    "query": text,
                    "rationale": q.get("rationale", ""),
                    "nes_id": nes_id,
                    "card": card,
                })
        labels[qid] = d

    if pending:
        _PENDING_PATH.write_text(json.dumps(pending, ensure_ascii=False, indent=1))
        logging.warning(
            "%d (query, profile) pairs are UNJUDGED (treated as grade 0 for this "
            "run). Wrote %s. Run the subagent judge to grade them — this module "
            "never calls the paid API. See eval/semantic/README.md.",
            len(pending), _PENDING_PATH.name,
        )
    else:
        _PENDING_PATH.unlink(missing_ok=True)
    return labels


# The relevance rubric — kept here as the single source of truth so the subagent
# judge (judge_subagents.js) grades with the SAME criteria. (Not used to call any
# API from this process.)
RUBRIC = """\
Rate how well an alumni profile satisfies the searcher's INTENT:
3 = Ideal (exactly the kind of person wanted); 2 = Relevant (genuinely satisfies
it); 1 = Marginal (loosely related); 0 = Irrelevant.
Judge by MEANING with world knowledge (XTX/Pinely -> relevant to "HFT"; "Sales
Manager" -> relevant to "продажи"; Bocconi -> an Italian university). Weigh job
titles, employers, expertise, NES program, pre-NES university & specialty, city,
hobbies, and bio. NAME queries: only the actual person(s) named are 3, else 0.
Location/employer/title queries: the attribute must actually match to score >= 2.
Be strict about 3 vs 2."""
