"""
Interactive re-index of one profile after the user edits their bio ("About").

OpenSearch is a pure projection of Postgres: a profile is ONE unified document
(directory `SearchText` + the user's bio, enriched, embedded). So a bio edit
rebuilds the whole document from scratch rather than patching a separate "cv
side" — the two-sided model is gone.

Best-effort by design: the bio is already persisted to Postgres (the source of
truth and the profile-card display source) before this runs, so any failure here
is logged and swallowed. The next directory sync self-heals the index because the
bio is folded into the change hash (see `api/sync.py`).
"""

import asyncio
import logging

from nespresso.db.services.user_context import GetUserContextService
from nespresso.recsys.searching.document import (
    BuildProfileText,
    UpsertProfileOpenSearch,
)
from nespresso.recsys.searching.filtering import StructuredFields
from nespresso.recsys.searching.llm.enrich import EnrichTexts
from nespresso.recsys.searching.preprocessing.embedding import (
    CalculateTokenLen,
    CreateEmbedding,
)
from nespresso.recsys.searching.preprocessing.model import TOKEN_LEN


async def RebuildProfileForBio(nes_id: int, about: str) -> None:
    """
    Rebuild + re-index the unified profile document after a bio save:
    directory `SearchText` + bio -> enrich -> embed -> full-replace write.

    No-op if the user has no directory profile yet (bound to an id not mirrored
    from MyNES). Any indexing failure is logged and swallowed.
    """
    ctx = await GetUserContextService()
    nes_user = await ctx.GetNesUser(nes_id=nes_id)
    if nes_user is None:
        logging.debug(f"nes_id={nes_id}: no NesUser row; skipping bio re-index.")
        return

    try:
        text = BuildProfileText(nes_user, about)
        if CalculateTokenLen(text) > TOKEN_LEN:
            logging.warning(
                f"nes_id={nes_id}: unified profile text exceeds {TOKEN_LEN} "
                f"tokens; the embedding will truncate the tail."
            )
        enriched = (await EnrichTexts([text]))[0].text
        embedding = await asyncio.to_thread(CreateEmbedding, enriched)
        await UpsertProfileOpenSearch(
            nes_id, enriched, embedding, StructuredFields(nes_user)
        )
    except Exception:
        logging.warning(
            f"nes_id={nes_id}: bio re-index failed; the next sync will heal it.",
            exc_info=True,
        )
