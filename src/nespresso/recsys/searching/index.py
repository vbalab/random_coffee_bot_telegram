import logging
from dataclasses import dataclass
from enum import Enum

from nespresso.recsys.searching.client import client
from nespresso.recsys.searching.preprocessing.embedding import CreateEmbedding
from nespresso.recsys.searching.preprocessing.model import EMBEDDING_LEN

INDEX_NAME = "nes_users"


@dataclass
class DocAttr:
    text: str
    embedding: list[float]

    class Field(str, Enum):
        text = "text"
        embedding = "embedding"

    @classmethod
    def FromText(cls, text: str) -> "DocAttr":
        return cls(
            text=text,
            embedding=CreateEmbedding(text),
        )


# Structured `f_*` fields (stored in _source) for query-filter re-scoring + rerank
# cards. See recsys/searching/filtering.py. Controlled-vocab arrays MUST be keyword
# so the structured `terms` query matches exactly; free-text fields are text.
_STRUCTURED_PROPERTIES: dict = {
    "name": {"type": "text"},
    "f_sex": {"type": "keyword"},
    "f_city": {"type": "keyword"},
    "f_region": {"type": "keyword"},
    "f_country": {"type": "keyword"},
    "f_program": {"type": "keyword"},
    "f_class_year": {"type": "keyword"},
    "f_professional": {"type": "keyword"},
    "f_industry": {"type": "keyword"},
    "f_country_exp": {"type": "keyword"},
    "f_company": {"type": "text"},
    "f_universities": {"type": "text"},
    "f_role": {"type": "text"},
}


async def EnsureOpenSearchIndex() -> bool:
    """
    Create the index if it is missing, and ensure the structured `f_*` field
    mappings exist (so indices created before those fields existed map them as
    keyword, not dynamically as text).

    If a LEGACY two-sided mapping is found (`mynes_text` / `cv_text` from before
    the profile sides were unified into one `text` + `embedding`), the index is
    dropped and recreated: the field NAMES changed, so put_mapping cannot
    repurpose them, and a stale/absent KNN field would make vector search
    silently return nothing. A full re-embed is unavoidable anyway (the unified
    text is new content); the startup sync is blocking before polling, so an
    empty-then-repopulated index is fine.

    Returns True if the index was (re)created (so the directory sync forces a
    full re-index), False if a current unified index already existed.
    """
    if await client.indices.exists(index=INDEX_NAME):
        mapping = await client.indices.get_mapping(index=INDEX_NAME)
        props = mapping.get(INDEX_NAME, {}).get("mappings", {}).get("properties", {})
        legacy = "mynes_text" in props or DocAttr.Field.text.value not in props
        if legacy:
            logging.warning(
                "Legacy OpenSearch mapping detected; recreating index unified."
            )
            await client.indices.delete(index=INDEX_NAME)
            # fall through to create the unified index below
        else:
            await client.indices.clear_cache(index=INDEX_NAME, query=True)
            # Ensure the structured fields are mapped as keyword on pre-existing
            # indices (no-op if already present; the next sync populates them).
            try:
                await client.indices.put_mapping(
                    index=INDEX_NAME, body={"properties": _STRUCTURED_PROPERTIES}
                )
            except Exception:
                logging.warning(
                    "Could not ensure structured field mappings.", exc_info=True
                )
            return False

    properties: dict = {
        DocAttr.Field.text.value: {"type": "text"},
        DocAttr.Field.embedding.value: {
            "type": "knn_vector",
            "dimension": EMBEDDING_LEN,
        },
    }
    properties.update(_STRUCTURED_PROPERTIES)

    create_body = {
        "settings": {"index.knn": True},
        "mappings": {"properties": properties},
    }

    await client.indices.create(index=INDEX_NAME, body=create_body)
    logging.info(f"# OpenSearch '{INDEX_NAME}' index created.")
    return True


# TODO: remove this later
async def DeleteOpenSearchIndex() -> None:
    await client.indices.delete(index=INDEX_NAME)
    logging.info(f"# OpenSearch '{INDEX_NAME}' index deleted.")
