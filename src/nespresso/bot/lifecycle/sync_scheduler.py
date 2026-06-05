"""
Background scheduler for the periodic MyNES directory sync.

A plain asyncio task (no external scheduler process) that refreshes the directory
every `MYNES_SYNC_INTERVAL_SECONDS`. The blocking *startup* sync runs in
`__main__` before polling begins, so this loop only handles the recurring
refreshes — it sleeps first, then syncs. The sync itself is concurrency-guarded,
so a long run can never overlap the next tick or a manual admin-triggered sync.
"""

import asyncio
import logging

from nespresso.api.sync import SyncFromMyNES
from nespresso.core.configs.settings import settings

_task: asyncio.Task[None] | None = None


async def _Loop() -> None:
    while True:
        await asyncio.sleep(settings.MYNES_SYNC_INTERVAL_SECONDS)
        try:
            await SyncFromMyNES(trigger="scheduled")
        except asyncio.CancelledError:
            raise
        except Exception:
            # SyncFromMyNES already swallows its own errors, but guard anyway so
            # a transient failure never kills the scheduling loop.
            logging.exception("MyNES sync raised unexpectedly.")


def StartSyncScheduler() -> None:
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_Loop())
    logging.info(
        "MyNES sync scheduler started "
        f"(every {settings.MYNES_SYNC_INTERVAL_SECONDS}s)."
    )


async def StopSyncScheduler() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None
    logging.info("MyNES sync scheduler stopped.")
