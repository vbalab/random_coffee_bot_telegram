"""
Hourly synchronization of the local stores (Postgres `nes_user` + OpenSearch)
with the MyNES directory feed (`GET /user/list`).

The feed is the single source of truth for alumni *profile* data. Each run:

  1. Fetches the full directory and dedupes it (the feed contains byte-identical
     duplicate rows) down to one record per alumni nes_id.
  2. Computes a content hash per profile and does work ONLY for changed/new/
     relisted profiles — OR profiles missing from the OpenSearch index (a
     presence check that self-heals a partially-lost index): re-embeds +
     re-indexes them, and upserts only those rows (overwriting removed fields
     with NULL; `created_at` is preserved). Unchanged-listed-present profiles
     cost nothing beyond the hash/presence compare, so the steady-state hourly
     run is dominated by the single ~4 MB feed fetch.
  4. Delists anyone who dropped out of the directory: marks `listed = False`
     and removes their OpenSearch document so they stop being searchable /
     matchable. The row is kept so existing references don't break.

The feed now carries `email`, `sex`, and `programs` (name+year), so this path
writes `nes_email`/`sex`/`programs` (and the derived primary `program`/
`class_name`). `nes_email` is COALESCE-guarded in SyncUpsertNesUsers so a feed
that ever drops email cannot NULL an email already bound at registration (the
byEmail path); registration still resolves email -> nes_id via
`api.request.ResolveNesUserByEmail` (now DB-first for every alumnus).
"""

import asyncio
import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from nespresso.api.request import FetchUsersList
from nespresso.db.models.nes_user import NesUser
from nespresso.db.models.schemas.nes_user import NesUserIn
from nespresso.db.services.user_context import GetUserContextService
from nespresso.recsys.searching.document import (
    BulkDeleteOpenSearch,
    BulkUpsertMynesOpenSearch,
    PresentDocIds,
)
from nespresso.recsys.searching.filtering import StructuredFields
from nespresso.recsys.searching.index import EnsureOpenSearchIndex
from nespresso.recsys.searching.llm.enrich import EnrichTexts
from nespresso.recsys.searching.preprocessing.embedding import CreateEmbeddings

# How many profiles to embed + index per batch. Bounds peak memory (each batch
# holds N×768 floats) and lets the event loop breathe between `to_thread` calls.
_EMBED_BATCH = 256

# Bump to force a one-off full re-index (new doc text shape, new structured
# fields, enrichment, etc.): it is folded into the content hash, so every stored
# hash mismatches and the next sync re-embeds + rewrites every profile.
# v3: index-time world-knowledge enrichment before embedding.
# v4: feed added email + sex + programs; SearchText now includes program/year.
# v5: SearchText now also includes the education `department` (the feed populated
#     post_nes_education); a SearchText change is invisible to the feed-JSON hash,
#     so the version bump is what forces the re-embed.
_DOC_VERSION = "5"

# Columns written from the feed to `nes_user`. The directory feed now carries
# `email` (-> nes_email), `sex`, and `programs` (with program/class_name derived
# from the latest program), so all are written. `created_at` is omitted
# (preserved). `listed`, `synced_at`, `mynes_text_hash`, `updated_at` are set
# explicitly per row.
_PROFILE_COLUMNS = (
    "nes_id",
    "name",
    "nes_email",
    "sex",
    "city",
    "region",
    "country",
    "alumni",
    "program",
    "class_name",
    "programs",
    "hobbies",
    "industry_expertise",
    "country_expertise",
    "professional_expertise",
    "main_work",
    "additional_work",
    "pre_nes_education",
    "post_nes_education",
)

_sync_lock = asyncio.Lock()


@dataclass
class SyncReport:
    trigger: str = ""
    started_at: datetime | None = None
    duration_s: float = 0.0
    fetched: int = 0  # records returned by the feed (incl. duplicates)
    unique: int = 0  # distinct nes_ids
    alumni: int = 0  # distinct alumni processed
    upserted: int = 0  # rows written to nes_user
    changed: int = 0  # profiles whose text changed (needed re-embedding)
    reindexed: int = 0  # profiles successfully (re)indexed in OpenSearch
    index_errors: int = 0  # profiles that failed to index
    delisted: int = 0  # users removed from the directory this run
    busy: bool = False  # another sync was already running
    ok: bool = False
    error: str | None = None


# Last completed (non-busy) run, surfaced by the admin "Sync now" panel.
LAST_SYNC: SyncReport | None = None


def GetLastSync() -> SyncReport | None:
    """Most recent completed run (None until the first one finishes)."""
    return LAST_SYNC


def _Hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _ToModel(user: NesUserIn) -> NesUser:
    """Transient NesUser (not session-attached) used for FullDescription/columns."""
    model = NesUser(**user.model_dump(mode="json"))
    # The feed delivers program+year only inside `programs`; derive the scalar
    # program/class_name (primary = latest) for display + analytics, while the
    # full `programs` list is kept on the model for structured search.
    model.program, model.class_name = user.primary_program()
    return model


async def SyncFromMyNES(trigger: str) -> SyncReport:
    """
    Run one full directory sync. `trigger` is a free-form label for logs/UI
    (e.g. "scheduled" or "admin:<chat_id>"). Concurrency-guarded: if a sync is
    already running, returns immediately with ``busy=True`` (no-op).
    """
    global LAST_SYNC

    if _sync_lock.locked():
        logging.info(f"MyNES sync ({trigger}) skipped: another run in progress.")
        return SyncReport(trigger=trigger, busy=True)

    async with _sync_lock:
        report = SyncReport(trigger=trigger, started_at=datetime.now(timezone.utc))
        start = time.monotonic()
        try:
            await _RunSync(report)
            report.ok = True
        except Exception as e:
            report.error = repr(e)
            logging.exception(f"MyNES sync ({trigger}) failed.")
        finally:
            report.duration_s = round(time.monotonic() - start, 1)
            LAST_SYNC = report

        logging.info(
            "MyNES sync (%s) done: ok=%s fetched=%d alumni=%d upserted=%d "
            "changed=%d reindexed=%d index_errors=%d delisted=%d took=%.1fs",
            trigger,
            report.ok,
            report.fetched,
            report.alumni,
            report.upserted,
            report.changed,
            report.reindexed,
            report.index_errors,
            report.delisted,
            report.duration_s,
        )
        return report


async def _RunSync(report: SyncReport) -> None:
    users = await FetchUsersList()
    report.fetched = len(users)
    report.unique = len({u.nes_id for u in users})

    # Dedupe to one record per alumni nes_id (feed duplicates are identical;
    # non-alumni are not indexed/matched, mirroring the single-user path).
    by_id: dict[int, NesUserIn] = {}
    for user in users:
        if user.alumni and user.nes_id not in by_id:
            by_id[user.nes_id] = user
    report.alumni = len(by_id)

    if not by_id:
        # Empty/failed feed: do nothing rather than delist the entire directory.
        logging.warning("MyNES sync: feed produced no alumni; skipping write/delist.")
        return

    now = report.started_at
    fresh_ids = list(by_id.keys())

    # Content hash per profile, used to skip unchanged work. It is taken from the
    # canonical pydantic JSON (fixed field order) — NOT from FullDescription,
    # whose `set()`-based dedup reorders lines per process (PYTHONHASHSEED) and
    # would mark profiles "changed" after every restart.
    models: dict[int, NesUser] = {}
    new_hashes: dict[int, str] = {}
    for nes_id, user in by_id.items():
        models[nes_id] = _ToModel(user)
        new_hashes[nes_id] = _Hash(f"{_DOC_VERSION}:{user.model_dump_json()}")

    # Self-heal the search index. EnsureOpenSearchIndex recreates it if the data
    # volume was reset. Then reconcile against the documents ACTUALLY present:
    # a profile is (re)indexed if its content changed OR it is missing from the
    # index. The presence check is what repairs a PARTIAL loss (some docs wiped,
    # an earlier index failure, a half-restored backup) — without it the stored
    # hash says "unchanged" and the missing doc would never be repopulated,
    # silently dropping that user from Find search and matching. A full wipe is
    # just the all-missing special case.
    await EnsureOpenSearchIndex()
    present_ids = await PresentDocIds()

    ctx = await GetUserContextService()
    old_hashes = await ctx.GetNesUserHashes(fresh_ids)
    # "changed" = new, modified, previously-delisted (delist clears the stored
    # hash), OR missing from the index. Unchanged-listed-and-present profiles need
    # NO work this run — not re-embedding and not even a DB write — which is what
    # keeps the steady state cheap (typically a handful of rows, not all ~3k).
    changed = [
        nid
        for nid in fresh_ids
        if new_hashes[nid] != old_hashes.get(nid) or nid not in present_ids
    ]
    report.changed = len(changed)

    # Surface a silent partial-index loss: profiles the DB thinks are indexed
    # (hash matches) yet are absent from the index — these are now being healed.
    missing = sum(
        1
        for nid in fresh_ids
        if nid not in present_ids and new_hashes[nid] == old_hashes.get(nid)
    )
    if missing:
        logging.warning(
            f"MyNES sync: {missing} listed profiles were missing from the search "
            f"index despite an unchanged hash — re-indexing them (index had "
            f"{len(present_ids)} docs, feed has {len(fresh_ids)} listed)."
        )

    # Embed + index only changed profiles, batch by batch. Each batch is first
    # enriched with world-knowledge context (off the search hot path), then the
    # ENRICHED text is what we embed + index, so indirect queries (e.g. "HFT"
    # matching an "XTX" profile) retrieve correctly.
    texts = {nid: models[nid].SearchText() for nid in changed}
    failed_index: set[int] = set()
    for batch_start in range(0, len(changed), _EMBED_BATCH):
        batch = changed[batch_start : batch_start + _EMBED_BATCH]
        batch_texts = [texts[nid] for nid in batch]
        enriched = await EnrichTexts(batch_texts)
        embeddings = await asyncio.to_thread(CreateEmbeddings, enriched)
        items = [
            (nid, enriched[i], embeddings[i], StructuredFields(models[nid]))
            for i, nid in enumerate(batch)
        ]
        failed = await BulkUpsertMynesOpenSearch(items)
        failed_index |= failed
        report.reindexed += len(batch) - len(failed)
    report.index_errors = len(failed_index)

    # Upsert ONLY changed/new/relisted rows (a profile that failed to index gets
    # hash=None so the next run retries it). Unchanged-and-listed rows are left
    # untouched — they are already correct and still listed.
    rows: list[dict[str, Any]] = []
    for nes_id in changed:
        model = models[nes_id]
        row = {col: getattr(model, col) for col in _PROFILE_COLUMNS}
        row["listed"] = True
        row["synced_at"] = now
        row["updated_at"] = now
        if nes_id in failed_index:
            row["mynes_text_hash"] = None
        else:
            row["mynes_text_hash"] = new_hashes[nes_id]
        rows.append(row)

    await ctx.SyncUpsertNesUsers(rows)
    report.upserted = len(rows)

    # Delist everyone no longer in the directory and drop them from search.
    delisted_ids = await ctx.DelistMissingNesUsers(set(fresh_ids))
    report.delisted = len(delisted_ids)
    if delisted_ids:
        await BulkDeleteOpenSearch(delisted_ids)
