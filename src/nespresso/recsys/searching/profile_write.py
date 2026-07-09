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

import logging

from nespresso.db.services.user_context import GetUserContextService
from nespresso.recsys.searching.document import (
    BuildProfileText,
    DeleteUserOpenSearch,
    UpsertProfileOpenSearch,
)
from nespresso.recsys.searching.filtering import StructuredFields
from nespresso.recsys.searching.llm.enrich import EnrichTexts
from nespresso.recsys.searching.preprocessing.embedding import CreateEmbedding
from nespresso.recsys.searching.preprocessing.model import RunInference


async def RebuildProfileForBio(nes_id: int, about: str) -> None:
    """
    Rebuild + re-index the unified profile document after a bio save:
    directory `SearchText` + bio -> enrich -> embed -> full-replace write.

    No-op if the user has no directory profile yet (bound to an id not mirrored
    from MyNES). Any indexing failure is logged and swallowed.

    A DELISTED user (``listed=False`` — removed from the MyNES directory, i.e.
    opted out of discoverability) must NOT be put back into the searchable index
    just by editing their bio. Their bio is still persisted to ``TgUser.about``
    (the source of truth), so if they re-appear in the directory the next sync
    folds it back into a fresh index doc — nothing is lost. Until then we keep
    them out of search: skip the index write and drop any stale document.
    """
    ctx = await GetUserContextService()
    nes_user = await ctx.GetNesUser(nes_id=nes_id)
    if nes_user is None:
        logging.debug(f"nes_id={nes_id}: no NesUser row; skipping bio re-index.")
        return

    if not nes_user.listed:
        logging.info(
            f"nes_id={nes_id}: delisted (listed=False); bio saved to Postgres but "
            "not indexed — a re-list re-indexes it via sync."
        )
        await DeleteUserOpenSearch(nes_id)
        return

    try:
        text = BuildProfileText(nes_user, about)
        result = (await EnrichTexts([text]))[0]
        if result.skip:
            # Out of Claude credits: do NOT overwrite the existing (good, enriched)
            # document with un-enriched text. The bio is safely in Postgres; the next
            # sync re-enriches this profile once credits return (its hash mismatches
            # the new bio). Admins were already alerted by EnrichTexts.
            logging.warning(
                f"nes_id={nes_id}: Claude API out of credits; bio saved to Postgres "
                "but not re-indexed — the next sync enriches it once credits return."
            )
            return
        enriched = result.text
        # Serialized on the shared inference worker (tokenizer is not thread-safe);
        # CreateEmbedding logs its own truncation tripwire.
        embedding = await RunInference(CreateEmbedding, enriched)
        await UpsertProfileOpenSearch(
            nes_id, enriched, embedding, StructuredFields(nes_user)
        )
    except Exception:
        logging.warning(
            f"nes_id={nes_id}: bio re-index failed; the next sync will heal it.",
            exc_info=True,
        )
