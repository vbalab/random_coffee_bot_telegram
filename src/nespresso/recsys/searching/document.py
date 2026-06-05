import logging
from typing import Any

from opensearchpy.exceptions import NotFoundError

from nespresso.recsys.searching.client import client
from nespresso.recsys.searching.index import INDEX_NAME, DocAttr, DocSide
from nespresso.recsys.searching.preprocessing.keywords import ExtractKeywords

# Number of documents per `_bulk` request. Each mynes doc carries a 768-float
# embedding (~6 KB serialized), so a few hundred per request keeps bodies sane.
_BULK_CHUNK = 250

_MYNES_TEXT_FIELD = f"{DocSide.mynes.value}_{DocAttr.Field.text.value}"
_MYNES_EMBEDDING_FIELD = f"{DocSide.mynes.value}_{DocAttr.Field.embedding.value}"


async def UpsertTextOpenSearch(
    nes_id: int,
    side: DocSide,
    text: str,
    extra: dict[str, Any] | None = None,
) -> None:
    attr = DocAttr.FromText(text)

    doc: dict[str, Any] = {
        f"{side.value}_{DocAttr.Field.text.value}": attr.text,
        f"{side.value}_{DocAttr.Field.embedding.value}": attr.embedding,
    }
    if extra:
        doc.update(extra)

    body = {"doc_as_upsert": True, "doc": doc}

    await client.update(
        index=INDEX_NAME,
        id=nes_id,
        body=body,
    )

    logging.info(
        f"nes_id={nes_id} :: Document of '{side.value}' side upserted with text: {repr(text)}."
    )


async def UpsertAboutOpenSearch(nes_id: int, about_text: str) -> None:
    keywords = ExtractKeywords(about_text)
    enriched = f"{about_text}\n{keywords}" if keywords else about_text
    await UpsertTextOpenSearch(nes_id, DocSide.cv, enriched)


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


async def BulkUpsertMynesOpenSearch(
    items: list[tuple[int, str, list[float], dict[str, Any]]],
) -> set[int]:
    """
    Bulk-upsert the `mynes` side (text + embedding) plus the structured `f_*`
    filter fields for many users at once, used by the directory sync.
    `doc_as_upsert` preserves any existing `cv` (user bio) side. Returns the set
    of nes_ids whose write FAILED, so the caller can avoid recording a hash for
    them (forcing a retry next sync).
    """
    failed: set[int] = set()
    if not items:
        return failed

    for start in range(0, len(items), _BULK_CHUNK):
        chunk = items[start : start + _BULK_CHUNK]
        body: list[dict[str, Any]] = []
        for nes_id, text, embedding, fields in chunk:
            doc: dict[str, Any] = {
                _MYNES_TEXT_FIELD: text,
                _MYNES_EMBEDDING_FIELD: embedding,
            }
            doc.update(fields)
            body.append({"update": {"_index": INDEX_NAME, "_id": nes_id}})
            body.append({"doc": doc, "doc_as_upsert": True})

        response = await client.bulk(body=body)
        if response.get("errors"):
            for item in response.get("items", []):
                op = item.get("update", {})
                if op.get("error"):
                    failed.add(int(op["_id"]))
                    logging.warning(
                        f"Bulk mynes upsert failed for nes_id={op.get('_id')}: "
                        f"{op.get('error')}"
                    )

    indexed = len(items) - len(failed)
    logging.info(
        f"BulkUpsertMynesOpenSearch: {indexed} indexed, {len(failed)} failed."
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
