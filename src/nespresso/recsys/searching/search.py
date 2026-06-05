from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

from aiogram import types
from cachetools import TTLCache
from opensearchpy.exceptions import NotFoundError

from nespresso.core.configs.settings import settings
from nespresso.recsys.profile import Profile
from nespresso.recsys.searching.client import client
from nespresso.recsys.searching.filtering import (
    SOURCE_FIELDS,
    STRUCT_WEIGHT,
    CandidateCard,
    StructuredBoost,
    _uni_substrings,
)
from nespresso.recsys.searching.index import INDEX_NAME, DocAttr, DocSide
from nespresso.recsys.searching.llm.query_understanding import ParseQuery, QueryFilters
from nespresso.recsys.searching.llm.rerank import Rerank
from nespresso.recsys.searching.preprocessing.embedding import CreateEmbedding
from nespresso.recsys.searching.preprocessing.keywords import ExtractKeywords
from nespresso.recsys.searching.search_pipeline import PIPELINE_NAME

_TIMEOUT = 60  # alive for 1 hour
_FETCH_SIZE = (
    100  # fetch all results in one shot (scroll unsupported with hybrid queries)
)
_KNN_LIMIT = 30
_SCORE_THRESHOLD = 0.1  # drop semantic-only results below this normalized score
_DISPLAY_LIMIT = 50  # max results materialized into pages per search


@dataclass
class Page:
    scroll_id: str
    score: float
    number: int
    profile: Profile
    total: int = 0
    capped: bool = False  # True when more than `total` candidates matched
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
        pages = []
        for i, hit in enumerate(hits):
            page = await cls._FromHit(hit, scroll_id="", number=start_number + i)
            pages.append(page)
        return pages

    def GetFormattedText(self) -> str:
        if not self.final_text:
            denom = f"{self.total}+" if self.capped else str(self.total)
            label = f"[Page: {self.number + 1} / {denom}]"
            self.final_text = f"`{label}`\n\n{self.profile.DescribeProfile()}"

        return self.final_text


class ScrollingSearch:
    def __init__(self, exclude_nes_id: int | None = None) -> None:
        self.pages: list[Page] = []
        self.index: int = 0
        self._exclude_nes_id = exclude_nes_id

    def _SemanticBody(
        self, semantic: str, keywords: str, embedding: list[float]
    ) -> dict[Any, Any]:
        """Hybrid BM25 + KNN retrieval on the cleaned semantic query."""

        def _text_query(field: str) -> dict[Any, Any]:
            if keywords:
                return {
                    "bool": {
                        "should": [
                            {"match": {field: {"query": semantic}}},
                            {"match": {field: {"query": keywords, "boost": 0.5}}},
                        ]
                    }
                }
            return {"match": {field: semantic}}

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
                "bool": {"must_not": [{"ids": {"values": [str(self._exclude_nes_id)]}}]}
            }
        return {
            "size": _FETCH_SIZE,
            "_source": SOURCE_FIELDS,
            "query": {"hybrid": hybrid_query},
        }

    def _StructBody(self, filters: QueryFilters) -> dict[Any, Any] | None:
        """
        Retrieve candidates matching the structured filters. This is what gives
        recall to filter-led queries whose cleaned semantic text is sparse/empty
        (e.g. "кто работал в Сбербанке" → semantic="", company filter only).
        """
        should: list[dict[Any, Any]] = []
        if filters.professional_expertise:
            should.append({"terms": {"f_professional": filters.professional_expertise}})
        if filters.industry_expertise:
            should.append({"terms": {"f_industry": filters.industry_expertise}})
        if filters.country_expertise:
            should.append({"terms": {"f_country_exp": filters.country_expertise}})
        if filters.city:
            should.append({"match": {"f_city": filters.city}})
            should.append({"match": {"f_region": filters.city}})
        if filters.company:
            should.append({"match": {"f_company": filters.company}})
        if filters.university:
            for sub in _uni_substrings(filters.university):
                should.append({"match": {"f_universities": sub}})
        if not should:
            return None

        bool_query: dict[str, Any] = {"should": should, "minimum_should_match": 1}
        if self._exclude_nes_id is not None:
            bool_query["must_not"] = [{"ids": {"values": [str(self._exclude_nes_id)]}}]
        return {
            "size": _FETCH_SIZE,
            "_source": SOURCE_FIELDS,
            "query": {"bool": bool_query},
        }

    def _CurrentPage(self) -> Page:
        return self.pages[self.index]

    async def _Search(
        self, body: dict[Any, Any], use_pipeline: bool = True
    ) -> list[dict[Any, Any]]:
        params = {"search_pipeline": PIPELINE_NAME} if use_pipeline else None
        try:
            response = await client.search(index=INDEX_NAME, body=body, params=params)
        except NotFoundError:
            # Index missing (e.g. volume reset before the next sync recreated it).
            # Degrade to "no results"; the sync self-heals the index within the hour.
            logging.warning(f"search index '{INDEX_NAME}' missing; returning no hits.")
            return []
        return response["hits"]["hits"]

    async def HybridSearch(self, message: types.Message) -> Page | None:
        if self.pages:
            raise ValueError("HybridSearch() was called more than once.")
        if not message.text:
            raise ValueError("Expected message.text to be non-empty")

        text = message.text
        parsed = await ParseQuery(text)  # fallback-safe (raw text on failure)
        filters = parsed.filters
        semantic = parsed.semantic_query.strip() or text
        keywords = ExtractKeywords(semantic)
        embedding = CreateEmbedding(semantic)

        logging.info(
            f"chat_id={message.chat.id} :: query='{text}' semantic='{semantic}' "
            f"keywords='{keywords}'"
        )

        # Candidate pool: nes_id -> (base hybrid score, _source).
        pool: dict[int, tuple[float, dict[Any, Any]]] = {}
        for hit in await self._Search(self._SemanticBody(semantic, keywords, embedding)):
            pool[int(hit["_id"])] = (float(hit["_score"]), hit.get("_source") or {})

        struct_body = self._StructBody(filters)
        if struct_body is not None:
            for hit in await self._Search(struct_body, use_pipeline=False):
                nid = int(hit["_id"])
                if nid not in pool:
                    pool[nid] = (0.0, hit.get("_source") or {})

        if not pool:
            return None

        # Combine: structured matches dominate; hybrid score breaks ties. Keep a
        # candidate if it matches a filter (boost>0) or is semantically relevant.
        scored: list[tuple[float, int, dict[Any, Any]]] = []
        for nid, (base, source) in pool.items():
            boost = StructuredBoost(filters, source)
            if boost > 0 or base >= _SCORE_THRESHOLD:
                scored.append((STRUCT_WEIGHT * boost + base, nid, source))
        if not scored:
            return None
        scored.sort(key=lambda x: x[0], reverse=True)
        capped = len(scored) > _DISPLAY_LIMIT  # more matched than we materialize
        scored = scored[:_DISPLAY_LIMIT]

        order_ids = [nid for _, nid, _ in scored]
        if settings.RERANK_ENABLED and len(scored) > 1:
            window = scored[: settings.RERANK_CANDIDATES]
            candidates = [(nid, CandidateCard(src)) for _, nid, src in window]
            reranked = await Rerank(text, candidates)
            order_ids = reranked + [
                nid for _, nid, _ in scored[settings.RERANK_CANDIDATES :]
            ]

        total = len(order_ids)
        pages: list[Page] = [
            Page(
                scroll_id="",
                score=0.0,
                number=i,
                total=total,
                capped=capped,
                profile=await Profile.FromNesId(nid),
            )
            for i, nid in enumerate(order_ids)
        ]
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
        return self.index < len(self.pages) - 1

    async def ScrollForward(self) -> Page | None:
        if not self.pages:
            raise ValueError("HybridSearch() must be called before scrolling forward.")

        if self.index >= len(self.pages) - 1:
            return None

        self.index += 1
        return self._CurrentPage()

    async def FinishScrolling(self) -> None:
        pass  # No scroll context to clear; all results fetched upfront


SEARCHES: TTLCache[uuid.UUID, ScrollingSearch] = TTLCache(
    maxsize=5000,
    ttl=_TIMEOUT * 60,
)
