import logging
from dataclasses import dataclass
from enum import Enum

from nespresso.recsys.searching.client import client
from nespresso.recsys.searching.preprocessing.embedding import CreateEmbedding
from nespresso.recsys.searching.preprocessing.model import EMBEDDING_LEN

INDEX_NAME = "nes_users"


class DocSide(str, Enum):
    mynes = "mynes"
    cv = "cv"


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
}


async def EnsureOpenSearchIndex() -> bool:
    """
    Create the index if it is missing, and ensure the structured `f_*` field
    mappings exist (so indices created before those fields existed map them as
    keyword, not dynamically as text). Returns True if the index was just created
    (so the directory sync can force a full re-index), False if it already existed.
    """
    text_config = {"type": "text"}
    embedding_config = {"type": "knn_vector", "dimension": EMBEDDING_LEN}

    if await client.indices.exists(index=INDEX_NAME):
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

    fields = [
        (DocSide.mynes, DocAttr.Field.text, text_config),
        (DocSide.mynes, DocAttr.Field.embedding, embedding_config),
        (DocSide.cv, DocAttr.Field.text, text_config),
        (DocSide.cv, DocAttr.Field.embedding, embedding_config),
    ]
    properties: dict = {
        f"{side.value}_{field.value}": config for side, field, config in fields
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
