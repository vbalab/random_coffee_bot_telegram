import logging

from opensearchpy.exceptions import NotFoundError

from nespresso.recsys.searching.client import client
from nespresso.recsys.searching.index import INDEX_NAME, DocAttr, DocSide
from nespresso.recsys.searching.preprocessing.keywords import ExtractKeywords


async def UpsertTextOpenSearch(
    nes_id: int,
    side: DocSide,
    text: str,
) -> None:
    attr = DocAttr.FromText(text)

    body = {
        "doc_as_upsert": True,
        "doc": {
            f"{side.value}_{DocAttr.Field.text.value}": attr.text,
            f"{side.value}_{DocAttr.Field.embedding.value}": attr.embedding,
        },
    }

    await client.update(
        index=INDEX_NAME,
        id=nes_id,
        body=body,
        refresh=True,
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
            refresh=True,
        )
        logging.info(f"nes_id={nes_id} :: Document deleted.")
    except NotFoundError:
        logging.info(f"nes_id={nes_id} :: Document not found, nothing to delete.")
