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

_TIMEOUT = 60  # alive for 1 hour
_SCROLL_LIMIT = 1
_KNN_LIMIT = 30


@dataclass
class Page:
    scroll_id: str
    score: float
    number: int
    profile: Profile
    final_text: str | None = None

    @classmethod
    async def FromResponse(cls, response: dict[Any, Any], number: int) -> Page | None:
        hits = response["hits"]["hits"]
        assert len(hits) <= 1

        if not hits:
            return None

        hit = hits[0]
        nes_id = int(hit["_id"])

        return cls(
            scroll_id=response["_scroll_id"],
            score=float(hit["_score"]),
            number=number,
            profile=await Profile.FromNesId(nes_id),
        )

    def GetFormattedText(self) -> str:
        if not self.final_text:
            self.final_text = (
                f"`[Page: {self.number}]`\n\n{self.profile.DescribeProfile()}"
            )

        return self.final_text


class ScrollingSearch:
    def __init__(self) -> None:
        self.pages: list[Page] = []
        self.index: int = 0
        self.expired = False

    def _CreateBody(self, message: types.Message) -> dict[Any, Any]:
        if not message.text:
            raise ValueError("Expected message.text to be non-empty")

        attr = DocAttr.FromText(message.text)

        logging.info(f"chat_id={message.chat.id} :: Query text: '{attr.text}'")

        body = {
            "size": _SCROLL_LIMIT,
            "_source": False,
            "query": {
                "bool": {  # composite query
                    "should": [  # scores are summed
                        {
                            "match": {
                                f"{DocSide.mynes.value}_{DocAttr.Field.text.value}": attr.text,
                            }
                        },
                        {
                            "knn": {
                                f"{DocSide.mynes.value}_{DocAttr.Field.embedding.value}": {
                                    "vector": attr.embedding,
                                    "k": _KNN_LIMIT,
                                }
                            }
                        },
                        {
                            "match": {
                                f"{DocSide.cv.value}_{DocAttr.Field.text.value}": attr.text,
                            }
                        },
                        {
                            "knn": {
                                f"{DocSide.cv.value}_{DocAttr.Field.embedding.value}": {
                                    "vector": attr.embedding,
                                    "k": _KNN_LIMIT,
                                }
                            }
                        },
                    ]
                }
            },
        }

        return body

    def _CurrentPage(self) -> Page:
        return self.pages[self.index]

    async def HybridSearch(self, message: types.Message) -> Page | None:
        if self.pages:
            raise ValueError("HybridSearch() was called more than once.")

        body = self._CreateBody(message)

        response = await client.search(
            index=INDEX_NAME,
            body=body,
            scroll=f"{_TIMEOUT}m",
        )

        page = await Page.FromResponse(
            response=response,
            number=self.index,
        )
        if page:
            self.pages = [page]

        # TODO: check for score (if it is high enough) and output `None`

        return self._CurrentPage()

    def CanScrollFurtherBackward(self) -> bool:
        return self.index > 0

    async def ScrollBackward(self) -> Page:
        if self.index == 0:
            raise ValueError("Can't scroll further backward.")

        self.index -= 1

        return self._CurrentPage()

    def CanScrollFurtherForward(self) -> bool:
        return self.index < self.pages[-1].number or not self.expired

    async def ScrollForward(self) -> Page | None:
        if not self.pages:
            raise ValueError("HybridSearch() must be called before scrolling forward.")

        if self.index < self.pages[-1].number:
            self.index += 1
            return self._CurrentPage()

        if self.expired:
            return None

        try:
            response = await client.scroll(
                scroll_id=self.pages[-1].scroll_id,
                scroll=f"{_TIMEOUT}m",  # refresh
            )
        except Exception:
            self.expired = True
            return None

        page = await Page.FromResponse(
            response=response,
            number=self.index + 1,
        )

        if not page:
            self.expired = True
            return None

        # TODO: check for score (if it is high enough) and output `None`

        self.pages.append(page)
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
