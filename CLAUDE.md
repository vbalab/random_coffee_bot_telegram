# CLAUDE.md — NESpresso Bot

## Project Overview

**NESpresso** is a Telegram bot for New Economic School (NES) alumni networking. It enables alumni to:
- Register and verify their NES identity (email-based)
- Search for other alumni using semantic + keyword hybrid search
- Get automatically matched with another alumnus biweekly

**Entry point:** `python -m nespresso` → `src/nespresso/__main__.py`

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Telegram bot | Aiogram 3.x (async, FSM-driven) |
| REST API | FastAPI (minimal scaffolding) |
| Database | PostgreSQL 15 + SQLAlchemy 2.0 async + AsyncPG |
| Search engine | OpenSearch 3.0 (BM25 + KNN vector) |
| ML embeddings | Alibaba GTE multilingual (768-dim, via Sentence Transformers) |
| Keyword extraction | KeyBERT |
| Task scheduling | APScheduler 3.x |
| Email | aiosmtplib (Gmail SMTP) |
| Config | Pydantic BaseSettings (.env) |
| i18n | Custom JSON-based (EN, RU) |
| Infrastructure | Docker Compose (4 services) |

---

## Repository Structure

```
src/nespresso/
├── __main__.py              # Startup orchestrator
├── core/                    # Cross-cutting concerns
│   ├── configs/
│   │   ├── settings.py      # Pydantic settings (all env vars)
│   │   ├── paths.py         # Filesystem paths + EnsurePaths()
│   │   └── admin_store.py   # Persistent JSON admin list
│   └── logs/                # Logging setup (color JSON, bot.log/api.log)
│       ├── bot.py           # Bot logger setup
│       ├── api.py           # API logger setup
│       ├── flow.py          # LoggerStart() / LoggerShutdown()
│       └── settings.py      # Log format/level config
├── db/                      # Database layer
│   ├── base.py              # DeclarativeBase + IntoDict()
│   ├── models/
│   │   ├── tg_user.py       # TgUser model (Telegram identity)
│   │   ├── nes_user.py      # NesUser model (alumni profile)
│   │   ├── message.py       # Message model (audit log)
│   │   └── schemas/
│   │       └── nes_user.py  # Pydantic schema for NesUser API response
│   ├── repositories/        # Repository pattern (pure DB access)
│   │   ├── tg_user.py
│   │   ├── nes_user.py
│   │   ├── message.py
│   │   └── checking.py      # CheckColumnBelongsToModel(), CheckOnlyOneArgProvided()
│   ├── services/            # Business logic over repos
│   │   ├── user.py          # UserService (TgUser + NesUser)
│   │   ├── message.py       # MessageService
│   │   └── user_context.py  # UserContextService (unified facade)
│   └── session.py           # Async engine, session factory, EnsureDB()
├── bot/                     # Telegram bot
│   ├── lifecycle/
│   │   ├── creator.py       # Bot + Dispatcher + BOT_ID singletons
│   │   └── menu.py          # SetMenu() — register /start, /cancel commands
│   ├── handlers/
│   │   ├── client/
│   │   │   ├── commands/
│   │   │   │   ├── hub.py   # Hub panel: SendHub(), HubKeyboard(), back-navigation
│   │   │   │   ├── start.py # Registration FSM (5 states)
│   │   │   │   └── find.py  # Search FSM (2 states + pagination)
│   │   │   ├── email/
│   │   │   │   └── verification.py  # CreateCode(), SendCode()
│   │   │   └── register.py  # RegisterClientHandlers()
│   │   ├── admin/
│   │   │   ├── commands/
│   │   │   │   ├── admin.py     # Main panel + all action handlers
│   │   │   │   ├── back.py      # BackToAdminPanelCallbackData, BackToHubCallbackData
│   │   │   │   ├── blocking.py  # Block/unblock users sub-panel
│   │   │   │   ├── admins.py    # Admin list management sub-panel
│   │   │   │   ├── matching.py  # Pause/resume scheduler sub-panel
│   │   │   │   ├── send.py      # (stub)
│   │   │   │   ├── senda.py     # (stub)
│   │   │   │   ├── messages.py  # (stub)
│   │   │   │   └── logs.py      # (stub)
│   │   │   └── register.py      # RegisterAdminHandlers()
│   │   ├── common/
│   │   │   ├── commands/
│   │   │   │   ├── cancel.py    # /cancel clears FSM state
│   │   │   │   └── zero.py      # Fallback for unrecognized input
│   │   │   └── register.py      # RegisterHandlerCancel(), RegisterHandlerZeroMessage()
│   │   └── staff/               # (reserved, currently empty)
│   └── lib/
│       ├── hub_state.py     # HUB_MESSAGES: dict[chat_id → message_id] in-memory cache
│       ├── message/
│       │   ├── io.py        # SendMessage, SendDocument, SendMessagesToGroup, ReceiveMessage
│       │   ├── i18n.py      # t(), GetUserLanguage(), SetUserLanguage()
│       │   ├── checks.py    # CheckVerified()
│       │   ├── file.py      # SendTemporaryFileFromText(), ToJSONText()
│       │   ├── filters.py   # AdminFilter (checks admin_store)
│       │   ├── keyboard.py  # CreateReplyKeyboard() generic builder
│       │   └── middleware.py # MessageLoggingMiddleware, CallbackLoggingMiddleware
│       ├── chat/
│       │   ├── username.py  # GetTgUsername()
│       │   └── block.py     # BlockUser(), UnblockUser()
│       └── notifications/
│           ├── admin.py     # NotifyOnStartup(), NotifyOnShutdown()
│           ├── erroring.py  # SetExceptionHandlers(), AiogramExceptionHandler
│           └── pending.py   # ProcessPendingUpdates()
├── recsys/                  # Recommendation system
│   ├── profile.py           # Profile dataclass + DescribeProfile() + FromNesId()
│   ├── searching/
│   │   ├── preprocessing/
│   │   │   ├── model.py     # Load Alibaba GTE model (singleton)
│   │   │   ├── embedding.py # CreateEmbedding(), CalculateTokenLen()
│   │   │   └── keywords.py  # ExtractKeywords() via KeyBERT
│   │   ├── client.py        # AsyncOpenSearch client + CloseOpenSearchClient()
│   │   ├── index.py         # Index schema + EnsureOpenSearchIndex()
│   │   ├── document.py      # UpsertTextOpenSearch(), DeleteUserOpenSearch()
│   │   └── search.py        # ScrollingSearch class + TTLCache
│   └── matching/
│       ├── assign.py        # MatchUsers() derangement + SendMatchingInfo()
│       ├── schedule.py      # APScheduler job: StartMatching(), ShutdownMatching(), PauseMatching(), ResumeMatching()
│       └── emoji.py         # RandomEmoji() for match identity
├── api/
│   ├── app.py               # FastAPI app + lifespan
│   ├── request.py           # HTTP request helpers
│   └── routers/
│       └── nes_user.py      # (stub — TODOs only)
└── translations/
    ├── en.json
    └── ru.json
```

---

## Architecture & Module Relationships

### Layered Dependency Graph

```
bot/handlers
     │
     ▼
bot/lib  ←──────────────────────────────────┐
     │                                       │
     ▼                                       │
db/services/user_context  (unified facade)  │
     │                                       │
     ├── db/services/user    ←── db/repositories/tg_user
     │                       ←── db/repositories/nes_user
     └── db/services/message ←── db/repositories/message
                                      │
                                      ▼
                               db/session  (AsyncSession)
                                      │
                                      ▼
                               db/models (SQLAlchemy ORM)

recsys/searching ←── recsys/matching
                 ←── bot/handlers/client/commands/find.py

recsys/profile   ←── recsys/matching/assign.py

core/configs ←── everywhere (settings, paths, admin_store)
```

### Key Dependency Rules

- **Handlers** never import repos directly — always go through `UserContextService`.
- **Repos** contain only SQL — no business logic, no Telegram calls.
- **Services** wrap repos; `UserContextService` is the single entry point for handlers.
- **`recsys/`** is self-contained; it imports from `db/` for user data but not from `bot/`.
- **`bot/lib/message/io.py`** is the only place that calls Aiogram's bot methods for sending messages (except inline markups built in handlers).
- **`core/`** has no imports from other nespresso modules — only stdlib + third-party.
- **Admin handlers** all live under `bot/handlers/admin/commands/`; the stub files (send.py, senda.py, messages.py, logs.py) exist but real logic is in `admin.py`.

---

## Data Models

### `TgUser` — Telegram identity
| Column | Type | Notes |
|--------|------|-------|
| `chat_id` | BigInteger PK | Telegram chat ID |
| `nes_id` | BigInteger FK→NesUser | NES profile link |
| `nes_email` | String | indexed |
| `username` | String | Telegram @handle, indexed |
| `phone_number` | String | indexed |
| `language` | String | "en" or "ru" |
| `about` | String | Free-form bio |
| `panel_message_id` | BigInteger | Last active hub message ID (for single-instance hub) |
| `verified` | Boolean | Registration complete |
| `blocked` | Boolean | Admin-blocked |

### `NesUser` — Alumni profile (sourced from NES API)
| Column | Type | Notes |
|--------|------|-------|
| `nes_id` | BigInteger PK | |
| `name` | String | |
| `city/region/country` | String | |
| `program/class_name` | String | NES study program |
| `hobbies/industry_expertise/country_expertise/professional_expertise` | JSON array | Skills/interests |
| `main_work/additional_work` | JSON object | Employment |
| `pre_nes_education/post_nes_education` | JSON array | Education history |

**Key methods on `NesUser`:**
- `SelfDescription()` — hobbies + expertise as readable text
- `WorkDescription()` — employment summary
- `FullDescription()` — combined profile text (used for OpenSearch indexing)

### `Message` — Audit log
Stores every bot↔user message exchange with timestamp and side (`Bot`/`User` enum).

---

## Core Flows

### 1. User Registration (`/start`)

```
/start
  └─ if no language set → state: ChooseLanguage → reply keyboard EN/RU → SetUserLanguage()
  └─ if already verified → SendHub(chat_id) immediately
  └─ state: GetPhoneNumber  → request contact share → store phone
  └─ state: EmailGet        → free-text email input (must contain @nes.ru)
  └─ state: EmailConfirm    → CreateCode() → SendCode(email, code) via SMTP
                              user enters 6-digit code → validate
  └─ state: Terms           → send terms.pdf → user accepts
  └─ verified = True, FSM cleared → SendHub(chat_id)
```

### 2. Hub Panel (`/start` for verified users)

```
SendHub(chat_id)
  └─ Read panel_message_id from HUB_MESSAGES[chat_id] (in-memory)
     or fall back to TgUser.panel_message_id in DB (survives restarts)
  └─ Delete old hub message (if any)
  └─ Send new hub message with HubKeyboard (Find + Admin buttons)
  └─ Store new message_id in both HUB_MESSAGES[chat_id] and TgUser.panel_message_id

Hub navigation (in-place editing of single message):
  ├─ "Find person" → enters Find FSM
  ├─ "Admin panel" → edits hub message to show AdminPanel
  │     └─ sub-panels (Blocking, Admins, Matching) edit same message
  │     └─ "Back" → edits back to AdminPanel
  └─ "Back to hub" → edits back to HubKeyboard
```

### 3. Alumni Search (`/find` or hub button)

```
Find
  └─ state: Text   → user enters query text
                     CreateEmbedding(text) → 768-dim vector
                     HybridQuery(BM25 + KNN on mynes+cv fields)
                     OpenSearch returns ranked results
                     ScrollingSearch cached in TTLCache (60 min)
  └─ state: Forward → paginate with prev/next inline buttons
                      display NesUser profile for each result
```

### 4. Biweekly Matching (scheduled)

```
APScheduler: every odd week, Monday 12:00 MSK
  └─ GetVerifiedTgUsersChatId() → list of chat_ids
  └─ MatchUsers(chat_ids)       → random derangement (no self-pairs)
  └─ For each Pair:
       Profile.FromNesId(user)  → fetch TgUser + NesUser
       Profile.FromNesId(match)
       SendMatchingInfo()       → send each user the other's profile
       Rate-limited: AsyncLimiter(30/sec)
```

### 5. Admin Panel (hub button, admin users only)

Requires chat_id to be in `data/admins/admins.json` (checked via `admin_store.Contains()`).

Accessed via Hub → "Admin panel" button (edits hub message in-place).

Actions: Send DM | Broadcast | View messages | Block/Unblock | Manage admins | Control matching schedule | Download logs

---

## Service Layer Details

### `UserContextService`

The **central facade** used by all handlers:

```python
# Created via factory — DO NOT instantiate directly
ctx = await GetUserContextService()

# TgUser operations
await ctx.RegisterTgUser(chat_id)           # create new TgUser
await ctx.GetTgUser(chat_id)                # full TgUser object
await ctx.GetTgUser(chat_id, TgUser.field)  # single column value
await ctx.UpdateTgUser(chat_id, TgUser.column, value)
await ctx.GetTgChatIdBy(tg_username="foo")  # lookup by various fields
await ctx.CheckTgUserExists(chat_id)        # bool
await ctx.GetVerifiedTgUsersChatId()        # list[int]

# NesUser operations
await ctx.GetNesUser(nes_id)
await ctx.UpsertNesUser([...])

# Message logging
await ctx.RegisterIncomingMessage(message)
await ctx.RegisterOutgoingMessage(message)
await ctx.GetRecentMessages(chat_id, limit=20)
```

### Repository Pattern

Each repo receives an `async_sessionmaker[AsyncSession]` and exposes typed async methods. All SQL lives here.

```
TgUserRepository methods:
  - CreateTgUser(chat_id)
  - GetTgUser(chat_id, column=None)       → TgUser | T | None
  - GetTgUsersOnCondition(condition, column=None)
  - GetChatIdBy(tg_username=...|nes_id=...|nes_email=...)
  - UpdateTgUser(chat_id, column, value)
```

---

## Recommendation System Details

### OpenSearch Index Schema

Index name: `nes_users`

Each document has 4 fields per "side" (`mynes` = alumni self-description, `cv` = CV/work info):
- `{side}_text` — analyzed text for BM25
- `{side}_embedding` — 768-dim `knn_vector` for ANN search

### Hybrid Search Query

```python
# Pseudocode for hybrid query in search.py
{
  "knn": [
    {"mynes_embedding": {"vector": embedding, "k": K}},
    {"cv_embedding":    {"vector": embedding, "k": K}},
  ],
  "should": [
    {"match": {"mynes_text": query}},
    {"match": {"cv_text":    query}},
  ]
}
```

Results are ranked by combined BM25 + cosine similarity score.

### `ScrollingSearch` (search.py)

Stateful pagination class. Cached in `SEARCHES: TTLCache` (5000 entries, 60-min TTL).

```python
search = ScrollingSearch(query, embedding)
page = await search.ScrollForward()   # next page
page = await search.ScrollBackward()  # previous page
```

---

## Internationalization

All user-facing strings live in `translations/en.json` and `translations/ru.json`.

```python
from nespresso.bot.lib.message.i18n import t

text = t(lang, "key.path", name="Alice")
```

- `lang` comes from `TgUser.language`
- Template substitution with `**kwargs` via Python `.format()`
- Falls back gracefully if key missing

---

## Configuration

All config via `.env` file, loaded by `core/configs/settings.py` (Pydantic `BaseSettings`):

```
TELEGRAM_BOT_TOKEN=
EMAIL_ADDRESS=           # Gmail account for verification codes
EMAIL_PASSWORD=          # Gmail app password
POSTGRES_USER=
POSTGRES_PASSWORD=
POSTGRES_DB=
POSTGRES_HOST=
POSTGRES_PORT=
POSTGRES_DSN=            # assembled DSN for SQLAlchemy
OPENSEARCH_INITIAL_ADMIN_PASSWORD=
NES_API_BASE_URL=        # default: https://my.nes.ru/new-api-2
```

### Filesystem Paths (`core/configs/paths.py`)

`EnsurePaths()` is called at startup and creates:
```
data/
  logs/bot/bot.log
  logs/api/api.log
  admins/admins.json
  temp/
  recsys/embedding/model/   ← HuggingFace model cache
  recsys/opensearch/data/
```

### Admin Store

Persistent list of admin chat IDs stored in `data/admins/admins.json`. Default admin: `749410326`.

Used by `admin_store.Contains(chat_id)` to gate admin panel access and `AdminFilter` middleware.

---

## Docker Services

```
nespresso_db          postgres:15      :5432   healthcheck: pg_isready
nespresso_opensearch  opensearch:3.0.0 :9200   healthcheck: curl /_cluster/health
nespresso_bot         (custom image)           depends_on: db, opensearch
nespresso_api         (custom image)   :8000   depends_on: db
```

All services share `nespresso_network` bridge.

---

## Startup Sequence (`__main__.py`)

```python
main():
1. EnsurePaths()              # Create required dirs/files
2. LoggerStart(LoggerSetup)   # Configure structured logging
3. EnsureDB()                 # Create PG tables if missing
4. EnsureOpenSearchIndex()    # Create OS index if missing
5. SetExceptionHandlers()     # Asyncio + Aiogram error handlers
6. dp.start_polling(bot, drop_pending_updates=True)

OnStartup() [registered as dp.startup hook]:
1. SetMenu()                  # Register /start, /cancel bot commands
2. RegisterHandlerCancel(dp)  # /cancel handler
3. RegisterAdminHandlers(dp)  # Admin panel routers
4. RegisterClientHandlers(dp) # Hub, start, find routers
5. RegisterHandlerZeroMessage(dp)  # Fallback handler
6. SetBotMiddleware(dp)       # Logging middleware
7. NotifyOnStartup()          # Send "Bot started" to all admins
8. ProcessPendingUpdates()    # Handle messages received while offline
9. StartMatching()            # Start APScheduler

OnShutdown() [registered as dp.shutdown hook]:
1. NotifyOnShutdown()         # Send bot.log to all admins
2. CloseOpenSearchClient()    # Graceful OpenSearch disconnect
3. ShutdownMatching()         # Stop APScheduler
4. LoggerShutdown()           # Flush logs
```

---

## Common Patterns

### Handler Structure

```python
router = Router()

class SomeStates(StatesGroup):
    First = State()
    Second = State()

@router.message(Command("cmd"))
async def handle_cmd(message: Message, state: FSMContext):
    ctx = await GetUserContextService()
    lang = await GetUserLanguage(message.chat.id)
    await SendMessage(chat_id=message.chat.id, text=t(lang, "some.key"))
    await state.set_state(SomeStates.First)
```

### Message Sending

Always use `bot/lib/message/io.py` — never call `bot.send_message()` directly:

```python
from nespresso.bot.lib.message.io import SendMessage, SendDocument

await SendMessage(chat_id=chat_id, text=text, reply_markup=kb)
await SendDocument(chat_id=chat_id, document=file, caption=text)
```

### Callback Buttons

Inline keyboards use Aiogram `CallbackData` subclasses for type-safe deserialization:

```python
class MyCallback(CallbackData, prefix="my"):
    action: str
    item_id: int

@router.callback_query(MyCallback.filter())
async def handle(query: CallbackQuery, callback_data: MyCallback):
    ...
```

### Hub Navigation (back buttons)

Use the shared `BackToHubCallbackData` and `BackToAdminPanelCallbackData` from `back.py`:

```python
from nespresso.bot.handlers.admin.commands.back import (
    BackToAdminPanelCallbackData,
    BackToHubCallbackData,
)

# Add to keyboard
InlineKeyboardButton(
    text="← Back",
    callback_data=BackToHubCallbackData().pack(),
)
```

The handlers for these are in `hub.py` (HubBack) and `admin.py` (PanelBack).

---

## Development Notes

- **No test suite** exists. Add tests under `tests/` following pytest-asyncio conventions.
- **API layer** (`api/routers/nes_user.py`) is a stub — all endpoints are TODOs.
- **Alembic** is listed as a dependency but no migration files exist yet; schema is created via `EnsureDB()` (metadata.create_all).
- The ML model (Alibaba GTE) is downloaded on first run to `data/recsys/embedding/model/` — ensure write permissions and network access.
- OpenSearch requires the `OPENSEARCH_INITIAL_ADMIN_PASSWORD` env var; TLS is disabled in dev config.
- Rate limiting for broadcasts uses `AsyncLimiter(30, 1)` — 30 messages per second — to stay within Telegram API limits.
- `HUB_MESSAGES` is an in-memory cache; `TgUser.panel_message_id` is the persistent DB-backed counterpart used to restore hub state after bot restarts.

---

## Glossary

| Term | Meaning |
|------|---------|
| `chat_id` | Telegram user/chat identifier (BigInteger) |
| `nes_id` | NES alumni database ID |
| `verified` | User completed full registration flow |
| `mynes` | NES alumni self-description side in OpenSearch |
| `cv` | CV/work experience side in OpenSearch |
| `ScrollingSearch` | Stateful paginated search session |
| `UserContextService` | Unified service facade used by handlers |
| `AdminStore` | JSON-backed persistent list of admin chat IDs |
| `derangement` | Permutation where no element maps to itself (matching algo) |
| `panel_message_id` | DB-persisted hub message ID; enables hub deletion across bot restarts |
| `HUB_MESSAGES` | In-memory `dict[chat_id → message_id]` for fast hub message tracking |
