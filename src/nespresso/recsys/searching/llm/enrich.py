"""
Index-time profile enrichment for Find search — INLINE contextual annotation.

Profiles describe themselves indirectly: someone employed at "XTX" / "Pinely"
never writes "high-frequency trading", so a query for "HFT" misses them. Neither
BM25 (no shared tokens) nor the small multilingual embedding reliably bridges
that gap — only world knowledge does.

The OLD approach appended a comma-separated KEYWORD BLOB to the profile text. It
helped BM25 but hurt the embedding: a detached bag of terms is out-of-distribution
for the (CLS-pooled, natural-language-trained) encoder and dilutes the single
profile vector.

This version keeps the world knowledge but changes its SHAPE. A fast Haiku call
rewrites the profile with short parenthetical glosses inserted IN PLACE, right
next to the entity each one explains — "Яндекс (крупная технологическая компания,
big tech, IT)", "ВШЭ, ФКН (strong CS school)". The result is ONE coherent
natural-language passage, in both Russian and English, that:
  - is embedding-friendly (glosses are grammatically attached to their entity,
    not a floating bag), and
  - still carries every world-knowledge token for exact BM25 matching,
so a single artifact now serves both retrieval channels well.

The annotation is ADDITIVE: the model preserves every original word and only INSERTs
context, verified by token retention. An unfaithful output is retried with a small
temperature (up to `_MAX_RETRIES`) — keeping the best-effort enriched result if none
is faithful (glosses beat raw text). A transient API error falls back to raw and is
flagged for the sync to re-attempt next run. So a flaky Claude API never breaks
indexing, and a cleared outage self-heals.

The reference block is `DIRECTORY_KNOWLEDGE` — the real organizations, universities
and roles that appear in our directory (frequency-grounded), so employers/schools
are glossed with their ACTUAL industry (incl. Russian firms and rebrands a generic
model gets wrong: Б1 = ex-EY, Технологии Доверия = ex-PwC, Alber Blanc / AIM Tech =
HFT). Its industry vocabulary matches the query-side `WORLD_KNOWLEDGE`, so both ends
of the match speak one language. It also lifts the system prompt past Haiku 4.5's
4096-token cache floor, so it is prompt-cached for large (reindex) batches — see
`EnrichTexts`.
"""

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any

from nespresso.core.configs.settings import settings
from nespresso.recsys.searching.llm.alerts import ReportLLMError
from nespresso.recsys.searching.llm.client import client
from nespresso.recsys.searching.llm.world_knowledge import DIRECTORY_KNOWLEDGE

# Headroom for the whole annotated profile (original + inline glosses) so a long
# profile is never truncated mid-annotation (which would fail validation and
# waste the call).
_MAX_TOKENS = 2000

# The annotation is additive, so the enriched text must retain (near) all of the
# original's significant tokens. Below this we assume the model rewrote/dropped
# content and fall back to the raw text.
_MIN_TOKEN_RETENTION = 0.9

# Prompt-cache the (~5k-token) system block only when the batch is at least this
# big — a reindex, where the cache write amortizes across thousands of calls. Below
# it (a small incremental sync or a single bio-save) caching would pay a 5-min
# cache write that is never read again.
_CACHE_MIN_BATCH = 16

# On an UNFAITHFUL output (retention < _MIN_TOKEN_RETENTION) retry with a small
# temperature: temperature 0 is deterministic, so a re-attempt reproduces the same
# bad output — a little sampling is the only way to get a different, hopefully
# faithful, result. If none is faithful after the retries, keep the best-retention
# enriched output (glosses beat the un-enriched raw text).
_MAX_RETRIES = 3
_RETRY_TEMPERATURE = 0.5

_SYSTEM_PROMPT = f"""\
You annotate a New Economic School (NES / РЭШ) alumni profile with brief \
world-knowledge context so it can be found by semantic search even when the \
searcher uses different words than the profile.

You are given the profile text. Return the SAME text, UNCHANGED, except that you \
INSERT a short parenthetical gloss immediately after the entities that benefit \
from context:
- after an EMPLOYER — its well-known name in the OTHER language if it differs, \
plus its industry / category. Examples: "Яндекс" -> "Яндекс (Yandex, крупная \
технологическая компания, big tech, IT)"; "Сбербанк" -> "Сбербанк (Sberbank, \
крупный российский банк / major Russian bank)". A name already written in Latin \
(e.g. "McKinsey", "XTX Markets") needs no transliteration.
- after a ROLE / position — the core skills or domain it implies, only if not \
already stated nearby. Example: "Quant Researcher" -> "Quant Researcher \
(алготрейдинг, статистика, машинное обучение / quantitative trading, statistics)".
- after a UNIVERSITY / faculty / program — its well-known name or abbreviation in \
the other language if it differs, plus its field or reputation. Example: "Высшая \
школа экономики, факультет компьютерных наук" -> "Высшая школа экономики (HSE), \
факультет компьютерных наук (сильная программа по computer science / strong CS \
school)".

Rules:
- PRESERVE every original word, line, number and fact verbatim — copy the \
original characters EXACTLY and never transliterate, re-spell, translate, \
reorder, remove or rewrite any existing text (keep Cyrillic letters Cyrillic). \
ONLY ADD parenthetical context, and never change a fact.
- Write each gloss in BOTH Russian and English and keep it SHORT (a few terms).
- Use only widely-known world knowledge. Do NOT invent personal facts (titles, \
employers, achievements, dates) that are not already in the text.
- Add a gloss only where it genuinely helps, and leave a line unchanged if it \
needs none. If the SAME named employer or school appears more than once, gloss \
ONLY its first occurrence and leave the later mentions exactly as they were.
- Output ONLY the annotated profile text, nothing else.

Reference knowledge — the organizations, universities and roles that appear in \
this alumni network, with their real industry / category. Use it to gloss \
employers and schools accurately, in both languages (it lists Russian firms and \
rebrands a generic model gets wrong — e.g. Б1 = ex-EY, Alber Blanc = HFT):

{DIRECTORY_KNOWLEDGE}

Example
Input:
Петров Пётр Петрович
Current position: Analyst at McKinsey
Professional expertise: стратегия, консалтинг
Post-NES education: МГУ, экономический факультет

Output:
Петров Пётр Петрович
Current position: Analyst at McKinsey (стратегический консалтинг, MBB / strategy \
consulting)
Professional expertise: стратегия, консалтинг
Post-NES education: МГУ, экономический факультет (МГУ им. Ломоносова / Lomonosov \
Moscow State University, top economics school)

Another example
Input:
Смирнова Анна
Current position: Quant at Alber Blanc
Previous position: Auditor at Б1

Output:
Смирнова Анна
Current position: Quant (алготрейдинг, статистика / quantitative trading, \
statistics) at Alber Blanc (высокочастотный трейдинг, HFT / high-frequency trading \
firm)
Previous position: Auditor at Б1 (ex-EY Russia, Big-4 аудит / Big-4 audit)

Example with a free-form bio (the user's own "About" is appended after the \
directory lines — gloss the employers / schools it names, keep the rest verbatim):
Input:
Козлов Дмитрий
Current position: Portfolio Manager at Сбербанк

Управляю портфелем облигаций; раньше строил модели в РЭШ и стажировался в BCG.

Output:
Козлов Дмитрий
Current position: Portfolio Manager at Сбербанк (Sberbank, крупный российский \
банк / major Russian bank)

Управляю портфелем облигаций; раньше строил модели в РЭШ (NES / Российская \
экономическая школа, экономические исследования / economic research) и \
стажировался в BCG (Boston Consulting Group, стратегический консалтинг, MBB / \
strategy consulting)."""

def _BuildSystem(cache: bool) -> list[dict[str, Any]]:
    """The system block, optionally prompt-cached (5-min ephemeral). Caching pays
    off only across a large batch (a reindex), so callers gate it by batch size."""
    block: dict[str, Any] = {"type": "text", "text": _SYSTEM_PROMPT}
    if cache:
        block["cache_control"] = {"type": "ephemeral"}
    return [block]

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def _FirstText(response: object) -> str:
    return "".join(b.text for b in response.content if b.type == "text")  # type: ignore[attr-defined]


def _SignificantTokens(text: str) -> set[str]:
    """Case-folded word tokens of length >= 3 (drops punctuation and noise)."""
    return {t.casefold() for t in _TOKEN_RE.findall(text) if len(t) >= 3}


def _Retention(original: str, enriched: str) -> float:
    """Fraction of the original's significant tokens present in the enriched text
    (1.0 = fully additive; low values mean the model rewrote/dropped content)."""
    orig = _SignificantTokens(original)
    if not orig:
        return 1.0 if enriched.strip() else 0.0
    return len(orig & _SignificantTokens(enriched)) / len(orig)


def _PreservesOriginal(original: str, enriched: str) -> bool:
    """True if the enriched text retains (near) all of the original's significant
    tokens — i.e. the model only ADDED context, it did not rewrite or drop facts."""
    return _Retention(original, enriched) >= _MIN_TOKEN_RETENTION


@dataclass
class EnrichResult:
    """
    One profile's enrichment outcome. `text` is what to index (enriched best-effort,
    or raw on failure). `retry` is True ONLY for a transient failure (API
    error/timeout) — the caller should force a re-attempt on the next sync (mark the
    change hash None), so an outage that clears (e.g. credits topped up) self-heals.
    A deterministic unfaithful output is NOT a retry: we already retried it with
    temperature and kept the best-effort result.
    """

    text: str
    retry: bool = False


async def _EnrichOne(
    text: str, semaphore: asyncio.Semaphore, system: list[dict[str, Any]]
) -> EnrichResult:
    """
    Inline-annotate one profile:
      - faithful (additive) output -> use it;
      - unfaithful output -> retry up to `_MAX_RETRIES` with a small temperature
        (sampling is the only way past a deterministic temperature-0 result); if
        none is faithful, keep the BEST-retention enriched output (glosses beat
        raw text);
      - transient API error/timeout -> raw text, flagged `retry` so the sync
        re-attempts next run (self-heals e.g. after a credit outage clears).
    """
    if not text.strip():
        return EnrichResult(text)
    first_line = text.splitlines()[0] if text.splitlines() else ""
    best_out: str | None = None
    best_ret = -1.0
    async with semaphore:
        for attempt in range(1 + _MAX_RETRIES):
            try:
                response = await client.with_options(
                    timeout=settings.ENRICH_TIMEOUT_SECONDS
                ).messages.create(
                    model=settings.ENRICH_MODEL,
                    max_tokens=_MAX_TOKENS,
                    # attempt 0 deterministic; retries sample to escape a bad output
                    temperature=0.0 if attempt == 0 else _RETRY_TEMPERATURE,
                    system=system,
                    messages=[{"role": "user", "content": text}],
                )
            except Exception as exc:
                # Transient (timeout / 5xx / out-of-credits): don't burn the other
                # attempts — fall back to raw and self-heal on the next sync.
                logging.warning(
                    "Enrichment attempt %d failed (%s); using raw text, will retry "
                    "next sync. [%s]",
                    attempt, type(exc).__name__, first_line, exc_info=True,
                )
                await ReportLLMError(exc, "enrichment")
                return EnrichResult(text, retry=True)
            out = _FirstText(response).strip()
            ret = _Retention(text, out) if out else 0.0
            if out and ret >= _MIN_TOKEN_RETENTION:
                if attempt:
                    logging.info(
                        "Enrichment faithful on retry %d/%d (retention %.2f). [%s]",
                        attempt, _MAX_RETRIES, ret, first_line,
                    )
                else:
                    logging.debug(f"enriched [{first_line}]: {out!r}")
                return EnrichResult(out)
            if out and ret > best_ret:
                best_ret, best_out = ret, out
            if attempt < _MAX_RETRIES:
                logging.info(
                    "Enrichment attempt %d %s; retrying at temperature %.1f. [%s]",
                    attempt,
                    "empty" if not out else f"unfaithful (retention {ret:.2f})",
                    _RETRY_TEMPERATURE,
                    first_line,
                )
        if best_out is not None:
            logging.warning(
                "Enrichment stayed unfaithful after %d retries (best retention "
                "%.2f); keeping best-effort enriched. [%s]",
                _MAX_RETRIES, best_ret, first_line,
            )
            return EnrichResult(best_out)
        logging.warning("Enrichment produced no output; using raw text. [%s]", first_line)
        return EnrichResult(text)


async def EnrichTexts(texts: list[str]) -> list[EnrichResult]:
    """
    Inline-annotate each profile (aligned 1:1 with input, fallback-safe). Returns an
    `EnrichResult` per input: `.text` is what to index, `.retry` flags a transient
    failure the caller should re-attempt next sync.

    The system prompt is prompt-cached only for large batches (a reindex), where the
    cache write amortizes across thousands of calls; a small incremental sync or a
    lone bio-save skips it (see `_CACHE_MIN_BATCH`).
    """
    if not settings.ENRICH_ENABLED or not texts:
        return [EnrichResult(t) for t in texts]

    system = _BuildSystem(cache=len(texts) >= _CACHE_MIN_BATCH)
    semaphore = asyncio.Semaphore(settings.ENRICH_CONCURRENCY)
    return await asyncio.gather(*(_EnrichOne(t, semaphore, system) for t in texts))
