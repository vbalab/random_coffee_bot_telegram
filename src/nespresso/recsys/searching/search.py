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
    RoleIsDominant,
    StructuredBoost,
)
from nespresso.recsys.searching.index import INDEX_NAME, DocAttr
from nespresso.recsys.searching.llm.query_understanding import ParseQuery, QueryFilters
from nespresso.recsys.searching.llm.rerank import Rerank
from nespresso.recsys.searching.preprocessing.embedding import CreateEmbedding
from nespresso.recsys.searching.preprocessing.keywords import ExtractKeywords
from nespresso.recsys.searching.preprocessing.model import RunInference
from nespresso.recsys.searching.search_pipeline import PIPELINE_NAME

_TIMEOUT = 60  # alive for 1 hour
_FETCH_SIZE = (
    100  # fetch all results in one shot (scroll unsupported with hybrid queries)
)
_KNN_LIMIT = 30
_SCORE_THRESHOLD = 0.1  # drop semantic-only results below this normalized score
_DISPLAY_LIMIT = 30  # pages materialized per chunk; more load as the user scrolls
# Of the RERANK_CANDIDATES rerank slots, reserve this many for the strongest
# pure-semantic (base-only) candidates, so a high-frequency filter can't flood the
# window and evict them before the reranker sees them. (25 combined + 5 semantic.)
_RERANK_SEMANTIC_SLOTS = 5


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
        self, semantic: str, keywords: str, embedding: list[float]
    ) -> dict[Any, Any]:
        """Hybrid BM25 + KNN retrieval on the bilingual semantic query.

        Two sub-queries over the single unified profile field: BM25 on `text` +
        KNN on `embedding`. (Directory self-description and user bio are one
        document now, so there is no second "cv side" lane.)

        `semantic` is already a faithful RU+EN restatement of the query (see the
        parser), so it feeds both the Russian primary text and the English
        world-knowledge glosses in the index — no separate query-side expansion
        lane is needed; the index already carries the expansion on its own side.
        """

        def _text_query(field: str) -> dict[Any, Any]:
            should: list[dict[Any, Any]] = [{"match": {field: {"query": semantic}}}]
            if keywords:
                should.append({"match": {field: {"query": keywords, "boost": 0.5}}})
            if len(should) == 1:
                return {"match": {field: semantic}}
            return {"bool": {"should": should}}

        hybrid_query: dict[str, Any] = {
            "queries": [
                _text_query(DocAttr.Field.text.value),
                {
                    "knn": {
                        DocAttr.Field.embedding.value: {
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
        if filters.country:
            should.append({"match": {"f_country": filters.country}})
        if filters.company:
            should.append({"match": {"f_company": filters.company}})
        # f_role RECALL only when role is the dominant intent (see RoleIsDominant):
        # on compound queries the other filters supply recall and a role lane would
        # flood the pool with title-only matches.
        if RoleIsDominant(filters):
            should.append({"match": {"f_role": filters.role}})
        # No `university` recall clause: university matching flows through the
        # enrichment-glossed text (semantic lane) + the reranker, not a hand-coded
        # alias table. See StructuredBoost / DIRECTORY_KNOWLEDGE.
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
        # Both are CPU-bound (KeyBERT + GTE encode) and would otherwise BLOCK the
        # event loop, stalling every other user's query for the duration. Route
        # them off-loop via the shared single-worker inference executor — NOT a
        # bare to_thread/gather: KeyBERT and the encoder share one non-thread-safe
        # tokenizer, so concurrent calls raise "Already borrowed". Serialized here,
        # but the event loop stays free for other users' Haiku/OpenSearch I/O.
        keywords = await RunInference(ExtractKeywords, semantic)
        embedding = await RunInference(CreateEmbedding, semantic)

        logging.info(
            f"chat_id={message.chat.id} :: query='{text}' semantic='{semantic}' "
            f"keywords='{keywords}'"
        )

        # Candidate pool: nes_id -> (base hybrid score, _source).
        pool: dict[int, tuple[float, dict[Any, Any]]] = {}
        sem_hits = await self._Search(
            self._SemanticBody(semantic, keywords, embedding)
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

        # Structured signal, normalized like the BM25/KNN lanes. StructuredBoost is
        # a raw sum of per-filter weights; min-max it across the pool to [0,1] (the
        # pool min is always 0 — a no-match candidate), so it's one more normalized
        # signal comparable to `base`, not a step that dwarfs semantics. A strong
        # BM25/KNN candidate can thus out-rank a near-empty one-filter profile, and
        # both stay in the rerank window. Keep a candidate if it matches a filter or
        # is semantically relevant. (See STRUCT_WEIGHT.)
        boosts = {nid: StructuredBoost(filters, src) for nid, (_b, src) in pool.items()}
        boost_max = max(boosts.values(), default=0.0) or 1.0
        # Each entry: (combined_score, base, nid, source). `base` is kept so the
        # rerank window can reserve slots by PURE semantic score (below).
        scored: list[tuple[float, float, int, dict[Any, Any]]] = []
        for nid, (base, source) in pool.items():
            if boosts[nid] > 0 or base >= _SCORE_THRESHOLD:
                struct = STRUCT_WEIGHT * boosts[nid] / boost_max
                scored.append((base + struct, base, nid, source))
        if not scored:
            # min-max normalization flattens a lone / all-equal-score hit to base~0,
            # so a single legitimate match with no structured boost would fall below
            # _SCORE_THRESHOLD and be dropped — reporting a false "nothing found".
            # We DID retrieve candidates, so keep them (ranked by base + struct).
            for nid, (base, source) in pool.items():
                struct = STRUCT_WEIGHT * boosts[nid] / boost_max
                scored.append((base + struct, base, nid, source))
        if not scored:
            return None
        scored.sort(key=lambda x: x[0], reverse=True)  # by combined score

        # Rerank the top window; the tail keeps re-score order (paginated lazily).
        # The window is NOT simply the top-N by combined score: a high-frequency
        # filter lifts ALL its matchers above every non-matcher, so >N matchers
        # would fill the window and evict genuinely-relevant profiles before the
        # reranker ever sees them. So reserve the last `_RERANK_SEMANTIC_SLOTS` for
        # the strongest PURE-SEMANTIC (base-only) candidates not already included.
        order_ids = [nid for _, _, nid, _ in scored]
        if settings.RERANK_ENABLED and len(scored) > 1:
            n_combined = settings.RERANK_CANDIDATES - _RERANK_SEMANTIC_SLOTS
            window = scored[:n_combined]
            picked = {nid for _, _, nid, _ in window}
            semantic_extra = sorted(
                (s for s in scored[n_combined:] if s[2] not in picked),
                key=lambda x: x[1],  # base (pure semantic) desc
                reverse=True,
            )[:_RERANK_SEMANTIC_SLOTS]
            window = window + semantic_extra
            window_ids = {nid for _, _, nid, _ in window}
            candidates = [(nid, CandidateCard(src)) for _, _, nid, src in window]
            reranked = await Rerank(text, candidates)
            tail = [nid for _, _, nid, _ in scored if nid not in window_ids]
            order_ids = reranked + tail

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

    async def ScrollBackward(self) -> Page | None:
        # Mirrors ScrollForward's "nothing more" contract (return None) instead
        # of raising — a double-tap on Prev is a normal race (the first tap's
        # edited keyboard hasn't reached the client yet), not an error.
        if self.index == 0:
            return None

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

# How many live search sessions one chat_id may hold in SEARCHES at once. The
# global cache has no per-user limit on its own, so one user searching
# repeatedly could otherwise fill it and start evicting other users' still-live
# sessions early.
_MAX_SEARCHES_PER_USER = 5
_USER_SEARCH_IDS: dict[int, list[uuid.UUID]] = {}


def RegisterSearch(chat_id: int, search_id: uuid.UUID, search: ScrollingSearch) -> None:
    """Track a new search under SEARCHES, evicting this user's own oldest
    session first if they're already at the per-user cap."""
    ids = _USER_SEARCH_IDS.setdefault(chat_id, [])
    while len(ids) >= _MAX_SEARCHES_PER_USER:
        oldest = ids.pop(0)
        SEARCHES.pop(oldest, None)
    ids.append(search_id)
    SEARCHES[search_id] = search
