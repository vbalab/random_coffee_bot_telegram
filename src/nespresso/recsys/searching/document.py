import logging
from typing import Any

from opensearchpy.exceptions import NotFoundError

from nespresso.db.models.nes_user import NesUser
from nespresso.recsys.searching.client import client
from nespresso.recsys.searching.index import INDEX_NAME, DocAttr

# Number of documents per `_bulk` request. Each doc carries a 768-float
# embedding (~6 KB serialized), so a few hundred per request keeps bodies sane.
_BULK_CHUNK = 250

_TEXT_FIELD = DocAttr.Field.text.value
_EMBEDDING_FIELD = DocAttr.Field.embedding.value


def BuildProfileText(nes_user: NesUser, about: str | None) -> str:
    """
    The single retrieval text for a profile: the directory self-description
    (`SearchText`) followed by the user's own bio (`TgUser.about`), if any.

    This is the pre-enrichment, pre-embedding text and is what the sync's change
    hash is taken over, so BOTH writers (directory sync and the bio-save path)
    MUST build it identically — hence one shared function. `SearchText` is
    deterministic (no set()-based reordering), so the same (profile, bio) always
    yields the same string.
    """
    base = nes_user.SearchText()
    bio = (about or "").strip()
    if not bio:
        return base
    return f"{base}\n\n{bio}" if base else bio


async def UpsertProfileOpenSearch(
    nes_id: int, text: str, embedding: list[float], fields: dict[str, Any]
) -> None:
    """
    Write the whole unified document (text + embedding + structured `f_*`
    fields) with a FULL replace (`index`, not a partial `update`). OpenSearch is
    a pure projection of Postgres now — the doc is always rebuilt from the DB —
    so a full replace correctly drops fields that no longer apply.
    """
    doc: dict[str, Any] = {_TEXT_FIELD: text, _EMBEDDING_FIELD: embedding}
    doc.update(fields)

    await client.index(index=INDEX_NAME, id=nes_id, body=doc)

    logging.info(f"nes_id={nes_id} :: Profile document upserted: {text!r}.")


async def DeleteUserOpenSearch(nes_id: int) -> None:
    try:
        await client.delete(
            index=INDEX_NAME,
            id=nes_id,
        )
        logging.info(f"nes_id={nes_id} :: Document deleted.")
    except NotFoundError:
        logging.info(f"nes_id={nes_id} :: Document not found, nothing to delete.")


async def CountOpenSearchDocs() -> int:
    """Number of documents currently in the index (0 if freshly created/wiped)."""
    result = await client.count(index=INDEX_NAME)
    return int(result.get("count", 0))


async def PresentDocIds() -> set[int]:
    """
    All nes_ids currently present as documents in the index (empty set if the
    index is missing/empty).

    Lets the directory sync self-heal a PARTIALLY-lost index: a profile the DB
    records as indexed (its `mynes_text_hash` matches) but whose document is
    actually missing here would otherwise be skipped forever by the hash check.
    Scrolls so it is correct regardless of index size.
    """
    ids: set[int] = set()
    try:
        resp = await client.search(
            index=INDEX_NAME,
            body={"query": {"match_all": {}}, "_source": False, "size": 2000},
            scroll="1m",
        )
    except NotFoundError:
        return ids

    scroll_id = resp.get("_scroll_id")
    try:
        hits = resp["hits"]["hits"]
        while hits:
            for hit in hits:
                ids.add(int(hit["_id"]))
            resp = await client.scroll(scroll_id=scroll_id, scroll="1m")
            scroll_id = resp.get("_scroll_id")
            hits = resp["hits"]["hits"]
    finally:
        if scroll_id:
            try:
                await client.clear_scroll(scroll_id=scroll_id)
            except Exception:
                logging.debug("clear_scroll failed (non-fatal).", exc_info=True)

    return ids


async def BulkUpsertProfilesOpenSearch(
    items: list[tuple[int, str, list[float], dict[str, Any]]],
) -> set[int]:
    """
    Bulk-write the whole unified document (text + embedding + structured `f_*`
    fields) for many users at once, used by the directory sync. Each op is a
    FULL replace (`index`) — the doc is rebuilt from the DB every time, so there
    is no other side to preserve. Returns the set of nes_ids whose write FAILED,
    so the caller can avoid recording a hash for them (forcing a retry next sync).
    """
    failed: set[int] = set()
    if not items:
        return failed

    for start in range(0, len(items), _BULK_CHUNK):
        chunk = items[start : start + _BULK_CHUNK]
        body: list[dict[str, Any]] = []
        for nes_id, text, embedding, fields in chunk:
            doc: dict[str, Any] = {
                _TEXT_FIELD: text,
                _EMBEDDING_FIELD: embedding,
            }
            doc.update(fields)
            body.append({"index": {"_index": INDEX_NAME, "_id": nes_id}})
            body.append(doc)

        response = await client.bulk(body=body)
        if response.get("errors"):
            for item in response.get("items", []):
                op = item.get("index", {})
                if op.get("error"):
                    failed.add(int(op["_id"]))
                    logging.warning(
                        f"Bulk profile upsert failed for nes_id={op.get('_id')}: "
                        f"{op.get('error')}"
                    )

    indexed = len(items) - len(failed)
    logging.info(
        f"BulkUpsertProfilesOpenSearch: {indexed} indexed, {len(failed)} failed."
    )
    return failed


async def BulkDeleteOpenSearch(nes_ids: list[int]) -> None:
    """Bulk-delete whole documents (e.g. users delisted from the directory)."""
    if not nes_ids:
        return

    for start in range(0, len(nes_ids), _BULK_CHUNK):
        chunk = nes_ids[start : start + _BULK_CHUNK]
        delete_body: list[dict[str, Any]] = [
            {"delete": {"_index": INDEX_NAME, "_id": nes_id}} for nes_id in chunk
        ]

        response = await client.bulk(body=delete_body)
        if response.get("errors"):
            for item in response.get("items", []):
                op = item.get("delete", {})
                # A missing doc (status 404 / "not_found") is fine — nothing to
                # delete. Anything else is a real error worth surfacing.
                if op.get("error"):
                    logging.warning(
                        f"Bulk delete failed for nes_id={op.get('_id')}: "
                        f"{op.get('error')}"
                    )

    logging.info(f"BulkDeleteOpenSearch: {len(nes_ids)} documents removed.")
