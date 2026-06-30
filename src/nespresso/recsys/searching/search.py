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
_DISPLAY_LIMIT = 30  # pages materialized per chunk; more load as the user scrolls
_EXPANSION_BOOST = 0.25  # world-knowledge query expansion: a gentle recall nudge only


@dataclass
class Page:
    number: int
    profile: Profile
    _body: str | None = None

    def GetProfileText(self) -> str:
        """Profile body (without the page-counter label — that is rendered live)."""
        if self._body is None:
            self._body = self.profile.DescribeProfile()
        return self._body


class ScrollingSearch:
    def __init__(self, exclude_nes_id: int | None = None) -> None:
        self.pages: list[Page] = []
        self.index: int = 0
        self._exclude_nes_id = exclude_nes_id
        # Full ranked nes_id list (reranked top chunk + re-score tail). Pages are
        # materialized lazily, _DISPLAY_LIMIT at a time, as the user scrolls.
        self._order_ids: list[int] = []
        # True when OpenSearch retrieval hit its size cap, so MORE matching
        # profiles may exist beyond the pool (shown to the user as "N+").
        self._pool_capped: bool = False

    def _SemanticBody(
        self, semantic: str, keywords: str, expanded: str, embedding: list[float]
    ) -> dict[Any, Any]:
        """Hybrid BM25 + KNN retrieval on the cleaned semantic query.

        The query-side world-knowledge `expanded` terms ride a separate, heavily
        down-weighted should-clause (`_EXPANSION_BOOST`): they widen *lexical*
        recall for narrow queries without letting world-knowledge tokens outvote
        the actual query. The embedding stays on the clean semantic text.
        """

        def _text_query(field: str) -> dict[Any, Any]:
            should: list[dict[Any, Any]] = [{"match": {field: {"query": semantic}}}]
            if keywords:
                should.append({"match": {field: {"query": keywords, "boost": 0.5}}})
            if expanded:
                should.append(
                    {"match": {field: {"query": expanded, "boost": _EXPANSION_BOOST}}}
                )
            if len(should) == 1:
                return {"match": {field: semantic}}
            return {"bool": {"should": should}}

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
        if filters.program:
            should.append({"terms": {"f_program": [filters.program]}})
        if filters.class_year:
            should.append({"term": {"f_class_year": str(filters.class_year)}})
        # gender (f_sex) is intentionally NOT a recall clause — MALE/FEMALE each
        # match ~half the directory and would flood the pool. It only re-scores
        # (StructuredBoost) candidates that another filter / the semantic pool
        # already surfaced.
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
        if not parsed.is_valid_search:
            # Non-bona-fide query (slur / abusive / not a real people search) —
            # surfaced to the user as a plain "nothing found".
            logging.info(
                f"chat_id={message.chat.id} :: query rejected by moderation: {text!r}"
            )
            return None
        filters = parsed.filters
        semantic = parsed.semantic_query.strip() or text
        keywords = ExtractKeywords(semantic)
        expanded = parsed.expanded_terms if settings.QUERY_EXPANSION_ENABLED else ""
        embedding = CreateEmbedding(semantic)

        logging.info(
            f"chat_id={message.chat.id} :: query='{text}' semantic='{semantic}' "
            f"keywords='{keywords}' expanded='{expanded}'"
        )

        # Candidate pool: nes_id -> (base hybrid score, _source).
        pool: dict[int, tuple[float, dict[Any, Any]]] = {}
        sem_hits = await self._Search(
            self._SemanticBody(semantic, keywords, expanded, embedding)
        )
        for hit in sem_hits:
            pool[int(hit["_id"])] = (float(hit["_score"]), hit.get("_source") or {})

        struct_hits: list[dict[Any, Any]] = []
        struct_body = self._StructBody(filters)
        if struct_body is not None:
            struct_hits = await self._Search(struct_body, use_pipeline=False)
            for hit in struct_hits:
                nid = int(hit["_id"])
                if nid not in pool:
                    pool[nid] = (0.0, hit.get("_source") or {})

        if not pool:
            return None

        # If either retrieval filled its page, more matching profiles may exist
        # beyond the pool — surfaced to the user as "N+".
        self._pool_capped = (
            len(sem_hits) >= _FETCH_SIZE or len(struct_hits) >= _FETCH_SIZE
        )

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

        # Rerank only the top window; the tail keeps re-score order. The full list
        # is paginated lazily (a chunk of pages built on demand as the user scrolls).
        order_ids = [nid for _, nid, _ in scored]
        if settings.RERANK_ENABLED and len(scored) > 1:
            window = scored[: settings.RERANK_CANDIDATES]
            candidates = [(nid, CandidateCard(src)) for _, nid, src in window]
            reranked = await Rerank(text, candidates)
            order_ids = reranked + [
                nid for _, nid, _ in scored[settings.RERANK_CANDIDATES :]
            ]

        self._order_ids = order_ids
        await self._MaterializeNextChunk()  # first _DISPLAY_LIMIT pages
        if not self.pages:
            return None
        self.index = 0
        return self._CurrentPage()

    async def _MaterializeNextChunk(self) -> None:
        """Build the next _DISPLAY_LIMIT pages from the ranked id list (lazy)."""
        start = len(self.pages)
        for nes_id in self._order_ids[start : start + _DISPLAY_LIMIT]:
            self.pages.append(
                Page(number=len(self.pages), profile=await Profile.FromNesId(nes_id))
            )

    def _Denominator(self) -> str:
        loaded = len(self.pages)
        more = len(self._order_ids) > loaded or self._pool_capped
        return f"{loaded}+" if more else str(loaded)

    def CurrentText(self) -> str:
        """Render the current page with a live page counter (n / loaded[+])."""
        page = self.pages[self.index]
        label = f"[Page: {page.number + 1} / {self._Denominator()}]"
        return f"<code>{label}</code>\n\n{page.GetProfileText()}"

    def CanScrollFurtherBackward(self) -> bool:
        return self.index > 0

    async def ScrollBackward(self) -> Page:
        if self.index == 0:
            raise ValueError("Can't scroll further backward.")

        self.index -= 1

        return self._CurrentPage()

    def CanScrollFurtherForward(self) -> bool:
        # A materialized next page exists, or another chunk can still be loaded.
        return self.index < len(self.pages) - 1 or len(self._order_ids) > len(self.pages)

    async def ScrollForward(self) -> Page | None:
        if not self.pages:
            raise ValueError("HybridSearch() must be called before scrolling forward.")

        if self.index >= len(self.pages) - 1:
            if len(self._order_ids) <= len(self.pages):
                return None  # nothing more was retrieved
            await self._MaterializeNextChunk()

        self.index += 1
        return self._CurrentPage()

    async def FinishScrolling(self) -> None:
        pass  # No scroll context to clear; the candidate pool is held in memory.


SEARCHES: TTLCache[uuid.UUID, ScrollingSearch] = TTLCache(
    maxsize=5000,
    ttl=_TIMEOUT * 60,
)
