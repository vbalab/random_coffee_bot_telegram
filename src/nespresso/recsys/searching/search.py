from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from aiogram import types
from cachetools import TTLCache

from nespresso.recsys.profile import Profile
from nespresso.recsys.searching.client import client
from nespresso.recsys.searching.index import INDEX_NAME, DocAttr, DocSide
from nespresso.recsys.searching.preprocessing.embedding import CreateEmbedding
from nespresso.recsys.searching.preprocessing.keywords import ExtractKeywords
from nespresso.recsys.searching.search_pipeline import PIPELINE_NAME

_TIMEOUT = 60  # alive for 1 hour
_SCROLL_LIMIT = 5  # fetch a batch of 5 per OpenSearch round-trip
_KNN_LIMIT = 30
_SCORE_THRESHOLD = 0.1  # drop results below this normalized score [0, 1]


@dataclass
class Page:
    scroll_id: str
    score: float
    number: int
    profile: Profile
    final_text: str | None = None

    @classmethod
    async def _FromHit(cls, hit: dict[Any, Any], scroll_id: str, number: int) -> Page:
        nes_id = int(hit["_id"])
        return cls(
            scroll_id=scroll_id,
            score=float(hit["_score"]),
            number=number,
            profile=await Profile.FromNesId(nes_id),
        )

    @classmethod
    async def BatchFromResponse(
        cls,
        response: dict[Any, Any],
        start_number: int,
    ) -> list[Page]:
        hits = response["hits"]["hits"]
        scroll_id = response.get("_scroll_id", "")
        pages = []
        for i, hit in enumerate(hits):
            page = await cls._FromHit(hit, scroll_id=scroll_id, number=start_number + i)
            pages.append(page)
        return pages

    def GetFormattedText(self) -> str:
        if not self.final_text:
            self.final_text = (
                f"`[Page: {self.number}]`\n\n{self.profile.DescribeProfile()}"
            )

        return self.final_text


class ScrollingSearch:
    def __init__(self, exclude_nes_id: int | None = None) -> None:
        self.pages: list[Page] = []
        self.index: int = 0
        self.expired = False
        self._exclude_nes_id = exclude_nes_id

    def _CreateBody(
        self,
        text: str,
        keywords: str,
        embedding: list[float],
    ) -> dict[Any, Any]:
        def _text_query(field: str) -> dict[Any, Any]:
            """BM25 match, optionally boosted by extracted keywords."""
            if keywords:
                return {
                    "bool": {
                        "should": [
                            {"match": {field: {"query": text}}},
                            {"match": {field: {"query": keywords, "boost": 0.5}}},
                        ]
                    }
                }
            return {"match": {field: text}}

        hybrid_query: dict[str, Any] = {
            "queries": [
                _text_query(f"{DocSide.mynes.value}_{DocAttr.Field.text.value}"),
                {
                    "knn": {
                        f"{DocSide.mynes.value}_{DocAttr.Field.embedding.value}": {
                            "vector": embedding,
                            "k": _KNN_LIMIT,
                        }
                    }
                },
                _text_query(f"{DocSide.cv.value}_{DocAttr.Field.text.value}"),
                {
                    "knn": {
                        f"{DocSide.cv.value}_{DocAttr.Field.embedding.value}": {
                            "vector": embedding,
                            "k": _KNN_LIMIT,
                        }
                    }
                },
            ]
        }

        if self._exclude_nes_id is not None:
            hybrid_query["filter"] = {
                "bool": {
                    "must_not": [{"ids": {"values": [str(self._exclude_nes_id)]}}]
                }
            }

        return {
            "size": _SCROLL_LIMIT,
            "_source": False,
            "query": {"hybrid": hybrid_query},
        }

    def _CurrentPage(self) -> Page:
        return self.pages[self.index]

    def _FilterByScore(self, pages: list[Page], start_number: int) -> list[Page]:
        """Drop low-relevance results and renumber sequentially from start_number."""
        filtered = [p for p in pages if p.score >= _SCORE_THRESHOLD]
        for i, p in enumerate(filtered):
            p.number = start_number + i
        return filtered

    async def HybridSearch(self, message: types.Message) -> Page | None:
        if self.pages:
            raise ValueError("HybridSearch() was called more than once.")

        if not message.text:
            raise ValueError("Expected message.text to be non-empty")

        text = message.text
        keywords = ExtractKeywords(text)
        embedding = CreateEmbedding(text)

        logging.info(
            f"chat_id={message.chat.id} :: Query text: '{text}' | keywords: '{keywords}'"
        )

        body = self._CreateBody(text, keywords, embedding)

        response = await client.search(
            index=INDEX_NAME,
            body=body,
            scroll=f"{_TIMEOUT}m",
            params={"search_pipeline": PIPELINE_NAME},
        )

        pages = await Page.BatchFromResponse(response, start_number=0)
        pages = self._FilterByScore(pages, start_number=0)

        if not pages:
            return None

        self.pages = pages
        return self._CurrentPage()

    def CanScrollFurtherBackward(self) -> bool:
        return self.index > 0

    async def ScrollBackward(self) -> Page:
        if self.index == 0:
            raise ValueError("Can't scroll further backward.")

        self.index -= 1

        return self._CurrentPage()

    def CanScrollFurtherForward(self) -> bool:
        return self.index < len(self.pages) - 1 or not self.expired

    async def ScrollForward(self) -> Page | None:
        if not self.pages:
            raise ValueError("HybridSearch() must be called before scrolling forward.")

        # Serve from buffer if available
        if self.index < len(self.pages) - 1:
            self.index += 1
            return self._CurrentPage()

        if self.expired:
            return None

        try:
            response = await client.scroll(
                scroll_id=self.pages[-1].scroll_id,
                scroll=f"{_TIMEOUT}m",  # refresh TTL
            )
        except Exception:
            self.expired = True
            return None

        new_pages = await Page.BatchFromResponse(response, start_number=len(self.pages))
        new_pages = self._FilterByScore(new_pages, start_number=len(self.pages))

        if not new_pages:
            self.expired = True
            return None

        self.pages.extend(new_pages)
        self.index += 1

        return self._CurrentPage()

    async def FinishScrolling(self) -> None:
        if not self.pages:
            raise ValueError(
                "HybridSearch() must be called before finishing scrolling."
            )

        await client.clear_scroll(scroll_id=self.pages[-1].scroll_id)


SEARCHES: TTLCache[uuid.UUID, ScrollingSearch] = TTLCache(
    maxsize=5000,
    ttl=_TIMEOUT * 60,
)
