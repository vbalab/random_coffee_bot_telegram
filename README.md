# NESpresso — NES Alumni Networking Bot

A Telegram bot for New Economic School (NES) alumni to find and connect with each other.

## What it does

- **Register** — verify your NES identity by email (`@nes.ru`).
- **Find people** — natural-language semantic + keyword search over the alumni
  directory, in Russian or English ("HFT quants in London", "выпускники ВШЭ").
- **Get matched** — admins run manual matching rounds that pair alumni for
  intros, with follow-up feedback collection.

## How search works

Each alumnus is one OpenSearch document (directory profile + self-written bio),
enriched at index time with inline world-knowledge glosses, then embedded. A
query is parsed by Claude into a moderation gate, a bilingual `semantic_query`,
and structured filters (company, role, university, expertise, location, …).
Retrieval fuses a hybrid **BM25 + KNN** pool with a structured `f_*` filter pool,
re-scores, and reranks the top results — all fallback-safe if the LLM is
unavailable. See [CLAUDE.md](CLAUDE.md) for the full architecture.

## Tech stack

| Layer | Tech |
|-------|------|
| Bot | Aiogram 3 (async, FSM) |
| API | FastAPI |
| DB | PostgreSQL 15 + SQLAlchemy 2 (async) |
| Search | OpenSearch 3 (hybrid BM25 + KNN) |
| Embeddings | Alibaba GTE multilingual (768-d) |
| Query understanding | Claude Haiku (parse, rerank, index-time enrichment) |

## Run

```bash
cp .env.example .env      # fill in tokens, DB creds, CLAUDE_API_KEY, …
docker compose up -d --build
```

Services: `db`, `opensearch`, `bot`, `api`. On startup the bot creates its schema
and indexes and mirrors the MyNES directory, then syncs hourly.

Locally, without Docker:

```bash
pip install -e .
python -m nespresso
```

## Layout

```
src/nespresso/
├── bot/        # Telegram handlers, keyboards, i18n
├── db/         # models, repositories, services
├── recsys/     # search (retrieval + LLM query understanding) + matching
├── api/        # FastAPI app + MyNES directory sync
└── core/       # settings, logging, admin store
eval/           # Find-search evaluation harness (nDCG / precision / recall)
```

## Configuration

All settings come from `.env` (see `.env.example`): Telegram token, Gmail SMTP for
verification codes, Postgres DSN, OpenSearch password, `CLAUDE_API_KEY`, and
tunables for the LLM search pipeline.

## Development

- No formal test suite yet; add tests under `tests/` (pytest-asyncio).
- Search-quality changes are validated with the `eval/` harness.
