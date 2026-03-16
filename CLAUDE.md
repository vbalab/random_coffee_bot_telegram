# CLAUDE.md — NESpresso Bot

## Project Overview

**NESpresso** is a Telegram bot for New Economic School (NES) alumni networking. It enables alumni to:
- Register and verify their NES identity (email-based)
- Search for other alumni using semantic + keyword hybrid search
- Get manually matched with other alumni when an admin triggers a matching round

**Entry point:** `python -m nespresso` → `src/nespresso/__main__.py`

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Telegram bot | Aiogram 3.x (async, FSM-driven) |
| REST API | FastAPI (minimal scaffolding) |
| Database | PostgreSQL 15 + SQLAlchemy 2.0 async + AsyncPG |
| Search engine | OpenSearch 3.0 (BM25 + KNN vector + normalization pipeline) |
| ML embeddings | Alibaba GTE multilingual (768-dim, via Sentence Transformers) |
| Keyword extraction | KeyBERT |
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
│   │   └── admin_store.py   # DB-backed admin list (GetAdminIds, IsAdmin, AddAdmin, RemoveAdmin)
│   └── logs/                # Logging setup (color JSON, bot.log/api.log)
│       ├── bot.py           # Bot logger setup
│       ├── api.py           # API logger setup
│       ├── flow.py          # LoggerStart() / LoggerShutdown()
│       └── settings.py      # Log format/level config
├── db/                      # Database layer
│   ├── base.py              # DeclarativeBase + IntoDict()
│   ├── models/
│   │   ├── __init__.py      # Imports all models so Base.metadata discovers them
│   │   ├── tg_user.py       # TgUser model (Telegram identity)
│   │   ├── nes_user.py      # NesUser model (alumni profile)
│   │   ├── message.py       # Message model (audit log)
│   │   ├── match.py         # MatchRound, MatchAssignment, MatchFeedback models
│   │   └── schemas/
│   │       └── nes_user.py  # Pydantic schema for NesUser API response
│   ├── repositories/        # Repository pattern (pure DB access)
│   │   ├── tg_user.py
│   │   ├── nes_user.py
│   │   ├── message.py
│   │   ├── match.py         # MatchRepository
│   │   ├── analytics.py     # AnalyticsRepository — aggregation queries for admin stats
│   │   └── checking.py      # CheckColumnBelongsToModel(), CheckOnlyOneArgProvided()
│   ├── services/            # Business logic over repos
│   │   ├── user.py          # UserService (TgUser + NesUser + GetAdminChatIds)
│   │   ├── message.py       # MessageService
│   │   ├── matching.py      # MatchingService (match rounds + assignments + feedback)
│   │   ├── user_context.py  # UserContextService (unified facade)
│   │   └── analytics.py     # AnalyticsService + GetAnalyticsService()
│   └── session.py           # Async engine, session factory, EnsureDB()
├── bot/                     # Telegram bot
│   ├── lifecycle/
│   │   ├── creator.py       # Bot + Dispatcher + BOT_ID singletons
│   │   └── menu.py          # SetMenu() — register /start, /cancel commands
│   ├── handlers/
│   │   ├── client/
│   │   │   ├── commands/
│   │   │   │   ├── hub.py      # Hub panel: SendHub(), HubKeyboard()
│   │   │   │   ├── start.py    # Registration FSM (6 states, incl. AboutNow)
│   │   │   │   ├── about.py    # About panel: view/edit user bio (hub sub-panel + FSM)
│   │   │   │   ├── find.py     # Search FSM (2 states + pagination)
│   │   │   │   └── settings.py # Settings sub-panel (matching toggle, language, help)
│   │   │   ├── email/
│   │   │   │   └── verification.py  # CreateCode(), SendCode(), TestEmail()
│   │   │   └── register.py  # RegisterClientHandlers()
│   │   ├── admin/
│   │   │   ├── commands/
│   │   │   │   ├── admin.py     # Main panel + all action handlers
│   │   │   │   ├── back.py      # BackToAdminPanelCallbackData, BackToHubCallbackData
│   │   │   │   ├── blocking.py  # Block/unblock users sub-panel
│   │   │   │   ├── admins.py    # Admin list management sub-panel (notifies other admins on changes)
│   │   │   │   ├── matching.py  # Run matching + send feedback request sub-panel
│   │   │   │   ├── statistics.py # Statistics sub-panel + DB export
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
│       │   ├── io.py        # SendMessage, SendDocument, SendMessagesToGroup, ReceiveMessage,
│       │   │                #   ReceiveCallback, PersonalMsg dataclass
│       │   ├── i18n.py      # t(), t_user(), GetUserLanguage(), GetUserLanguageOrNone(),
│       │   │                #   SetUserLanguage()
│       │   ├── checks.py    # CheckVerified()
│       │   ├── file.py      # SendTemporaryFileFromText(), ToJSONText(), SendTemporaryXlsxFile()
│       │   ├── filters.py   # AdminFilter (checks IsAdmin via DB)
│       │   ├── keyboard.py  # CreateReplyKeyboard() generic builder
│       │   └── middleware.py # MessageLoggingMiddleware, CallbackLoggingMiddleware,
│       │                    #   SetBotMiddleware()
│       ├── chat/
│       │   ├── username.py  # GetTgUsername(), GetChatUserLoggingPart()
│       │   └── block.py     # BlockUser(), UnblockUser(), CheckIfBlocked(), UserBlockedBot()
│       └── notifications/
│           ├── admin.py     # NotifyOnStartup(), NotifyOnShutdown()
│           ├── erroring.py  # SetExceptionHandlers(), AiogramExceptionHandler
│           └── pending.py   # ProcessPendingUpdates()
├── recsys/                  # Recommendation system
│   ├── profile.py           # Profile dataclass + DescribeProfile() + FromNesId() class method
│   ├── searching/
│   │   ├── preprocessing/
│   │   │   ├── model.py     # Load Alibaba GTE model (singleton)
│   │   │   ├── embedding.py # CreateEmbedding(), CalculateTokenLen()
│   │   │   └── keywords.py  # ExtractKeywords() via KeyBERT
│   │   ├── client.py        # AsyncOpenSearch client + CloseOpenSearchClient()
│   │   ├── index.py         # Index schema + EnsureOpenSearchIndex(), DocSide enum, DocAttr
│   │   ├── search_pipeline.py # EnsureSearchPipeline() — normalization pipeline for hybrid search
│   │   ├── document.py      # UpsertTextOpenSearch(), UpsertAboutOpenSearch(),
│   │   │                    #   DeleteUserOpenSearch()
│   │   └── search.py        # ScrollingSearch class + Page dataclass + SEARCHES TTLCache
│   └── matching/
│       ├── assign.py        # MatchUsers(), CreateMatching(), SendMatchingInfo(),
│       │                    #   MatchingPipeline() — core matching logic
│       ├── schedule.py      # RunMatching(triggered_by) — thin entry point (no scheduler)
│       └── emoji.py         # RandomEmoji() for match identity
├── api/
│   ├── app.py               # FastAPI app + lifespan
│   ├── request.py           # GetNesUserFromMyNES(), AllowDataSharingPermission(),
│   │                        #   DenyDataSharingPermission()
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
     ├── db/services/user     ←── db/repositories/tg_user
     │                        ←── db/repositories/nes_user
     ├── db/services/message  ←── db/repositories/message
     └── db/services/matching ←── db/repositories/match
                                      │
                                      ▼
                               db/session  (AsyncSession)
                                      │
                                      ▼
                               db/models (SQLAlchemy ORM)

recsys/searching ←── bot/handlers/client/commands/find.py

recsys/matching  ←── bot/handlers/admin/commands/matching.py
                 ←── db/services/user_context (for saving rounds/assignments)

recsys/profile   ←── recsys/matching/assign.py

core/configs/admin_store ←── bot/lib (filters, notifications)
                         ←── db/session (seeding on startup)

core/configs ←── everywhere (settings, paths, admin_store)
```

### Key Dependency Rules

- **Handlers** never import repos directly — always go through `UserContextService` or `AnalyticsService`.
- **Repos** contain only SQL — no business logic, no Telegram calls.
- **Services** wrap repos; `UserContextService` is the single entry point for handlers; `AnalyticsService` is the dedicated entry point for analytics/export queries.
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
| `nes_id` | BigInteger FK→NesUser | NES profile link, indexed, nullable |
| `nes_email` | String | indexed |
| `username` | String | Telegram @handle, indexed |
| `phone_number` | String | indexed |
| `language` | String | "en" or "ru" |
| `about` | String | Free-form bio |
| `panel_message_id` | BigInteger | Last active hub message ID (for single-instance hub) |
| `verified` | Boolean | Registration complete |
| `blocked` | Boolean | Admin-blocked |
| `matching_paused` | Boolean | User opted out of matching rounds (default False) |
| `is_admin` | Boolean | Admin privileges (default False) |
| `created_at` | DateTime | Server default CURRENT_TIMESTAMP |
| `updated_at` | DateTime | Server default CURRENT_TIMESTAMP |

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
- `SelfDescription()` — name, location, program/class
- `WorkDescription()` — employment summary
- `FullDescription()` — combined profile text (used for OpenSearch indexing)

### `Message` — Audit log
Stores every bot↔user message exchange with timestamp and side (`Bot`/`User` enum via `MessageSide`).

### `MatchRound` — Matching round record
| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | Auto-increment |
| `triggered_by` | BigInteger | chat_id of the admin who started the round |
| `created_at` | DateTime | |

### `MatchAssignment` — Directed match pair within a round
| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | Auto-increment |
| `round_id` | Integer FK→MatchRound | CASCADE delete |
| `assigner_chat_id` | BigInteger | User who was told to reach out |
| `assigned_chat_id` | BigInteger | User they were assigned to meet |
| `created_at` | DateTime | |

### `MatchFeedback` — User response to a feedback request
| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | |
| `assignment_id` | Integer FK→MatchAssignment | CASCADE delete |
| `response` | String | `"met"` / `"not_met"` / `"planning"` (see `FeedbackResponse` enum) |
| `created_at` | DateTime | |

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
  └─ verified = True
  └─ state: AboutNow        → inline prompt with 2 buttons:
                              [✏️ Write about now] → user types bio → saved → SendHub
                              [⏭ Write about later] → FSM cleared → SendHub
```

### 2. Hub Panel (`/start` for verified users)

```
SendHub(chat_id)
  └─ Read panel_message_id from HUB_MESSAGES[chat_id] (in-memory)
     or fall back to TgUser.panel_message_id in DB (survives restarts)
  └─ Delete old hub message (if any)
  └─ Send new hub message with HubKeyboard
  └─ Store new message_id in both HUB_MESSAGES[chat_id] and TgUser.panel_message_id

HubKeyboard buttons:
  ├─ "Find person"     → enters Find FSM
  ├─ "My About"        → edits hub message to About sub-panel
  ├─ "Settings"        → edits hub message to Settings sub-panel
  └─ "Admin panel"     → visible only to admins (is_admin=True); edits hub message to AdminPanel
        └─ sub-panels (Blocking, Admins, Matching, Statistics) edit same message
        └─ "Back" → edits back to AdminPanel
        └─ "Back to hub" → edits back to HubKeyboard
```

### 3. Settings Sub-panel (hub button)

```
Hub → "⚙️ Settings"
  └─ Edits hub message to Settings sub-panel
     Buttons:
       ├─ "Matching: On/Off" → toggles TgUser.matching_paused in-place (edits keyboard only)
       ├─ "🌐 Language"      → toggles TgUser.language between en/ru, re-renders settings panel
       ├─ "❓ Help"          → edits hub message to Help sub-panel
       │   └─ Help sub-panel buttons:
       │       ├─ "✉️ Ask for help" → notifies ALL admins: "Help request from @username (ID: chat_id)"
       │       └─ "⬅️ Back"        → edits hub message back to Settings sub-panel
       └─ "⬅️ Back"          → edits hub message back to HubKeyboard
```

### 4. About Panel (hub button)

```
Hub → "📝 My About"
  └─ Edits hub message to About sub-panel
     Header shows current TgUser.about (or "Not set yet." if empty)
     Buttons:
       ├─ "✏️ Write new about" → sends a separate message asking user to type bio
       │   └─ state: AboutStates.WriteAbout → user types text → saved to TgUser.about
       │      → UpsertAboutOpenSearch(nes_id, about_text) indexes bio with keyword extraction
       │      → state cleared → SendHub (fresh hub message)
       └─ "⬅️ Back" → edits hub message back to HubKeyboard
```

### 5. Alumni Search (hub button)

```
Find
  └─ state: Text   → user enters query text
                     ExtractKeywords(text) → comma-separated keywords for BM25 boosting
                     CreateEmbedding(text) → 768-dim vector
                     HybridSearch via normalization pipeline (BM25 + KNN on mynes+cv fields)
                     OpenSearch returns ranked + normalized results (score ≥ 0.1 threshold)
                     ScrollingSearch cached in SEARCHES TTLCache (5000 entries, 60 min)
  └─ state: Forward → paginate with prev/next inline buttons
                      display NesUser profile for each result
```

### 6. Manual Matching (admin-triggered)

There is **no automatic scheduler**. An admin must manually trigger each round.

```
Admin → Matching panel → "▶️ Run Matching Now"
  └─ Notify all OTHER admins: "X started a matching round"
  └─ Filter eligible users: verified=True, blocked=False, matching_paused=False, nes_id IS NOT NULL
  └─ Get excluded pairs from last 2 rounds (history-aware anti-repetition)
  └─ MatchUsers():
       Round 1: derangement avoiding excluded pairs → everyone gets ≥1 assignment
       Round 2: second derangement (if ≥3 users) avoiding round-1 pairs + excluded
       Result: each user gets 1 or 2 directed assignments (asymmetric)
  └─ Save MatchRound + all MatchAssignments to DB
  └─ Send each user their assigned profiles (i18n, rate-limited 30/sec)
  └─ Report count to admin
```

### 7. Feedback Collection (admin-triggered)

```
Admin → Matching panel → "📊 Send Feedback Request"
  └─ Fetch last MatchRound + its MatchAssignments from DB
  └─ For each assignment, send assigner:
       "Did you meet with [name]?" + [✅ Yes] [❌ No] [📅 Planning to] buttons
  └─ When user clicks → UpsertFeedback(assignment_id, response) stored in DB
  └─ Report sent count to admin
```

### 8. Admin Panel (hub button, admin users only)

Requires `TgUser.is_admin = True` in DB (checked via `IsAdmin(chat_id)` from `admin_store`).

Accessed via Hub → "Admin panel" button (edits hub message in-place).

Actions: Download logs | View user messages | Send DM | Broadcast | Block/Unblock | Run Matching / Send Feedback | Manage admins | Statistics

**Admin change notifications:** When an admin adds or removes another admin, all other admins receive a notification with who performed the action and who was affected.

### 9. Statistics Panel (admin sub-panel)

```
Admin Panel → 📊 Statistics → edits hub message to show Statistics sub-panel

Sub-panel buttons (each sends a new separate message with stats):
  ├─ 👥 Users    → total, verified/unverified, blocked, language split,
  │                profile completeness, new registrations (7d/30d)
  ├─ 🎓 Alumni   → total NesUser profiles, top 5 countries/cities/
  │                programs/industries/professional expertise
  ├─ 💬 Activity → total messages, bot/user split, today/week counts,
  │                top 5 most active users by message count
  ├─ 🤝 Matching → eligible users (verified non-blocked non-opted-out), opted-out count,
  │                total rounds run, last round date, last round assignments
  └─ ⬇️ Download DB → edits hub to Download DB sub-panel (Back → Statistics)
       ├─ 👤 tg_user  → sends tg_user.xlsx
       ├─ 🎓 nes_user → sends nes_user.xlsx
       └─ 💬 message  → sends message.xlsx
```

---

## Service Layer Details

### `UserContextService`

The **central facade** used by all handlers. Combines `UserService`, `MessageService`, and `MatchingService` via multiple inheritance.

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
await ctx.GetVerifiedTgUsersChatId()        # list[int] (verified only)
await ctx.GetAdminChatIds()                 # list[int] (is_admin=True)
await ctx.GetTgUsersOnCondition(condition, column)  # flexible filter

# NesUser operations
await ctx.GetNesUser(nes_id)
await ctx.UpsertNesUser([...])

# Message logging
await ctx.RegisterIncomingMessage(message)
await ctx.RegisterOutgoingMessage(message)
await ctx.GetRecentMessages(chat_id, limit=20)

# Matching
await ctx.CreateRound(triggered_by)                    # → MatchRound
await ctx.GetLastRound()                               # → MatchRound | None
await ctx.CreateAssignments(round_id, [(a, b), ...])   # → list[MatchAssignment]
await ctx.GetAssignmentsByRound(round_id)              # → list[MatchAssignment]
await ctx.GetRecentExcludedPairs(last_n_rounds=2)      # → set[tuple[int, int]]
await ctx.UpsertFeedback(assignment_id, response)
```

### `AnalyticsService`

Dedicated service for admin analytics and DB export — do **not** use `UserContextService` for these:

```python
svc = await GetAnalyticsService()

# Aggregated stats (return dicts)
await svc.GetTgUserStats()     # counts: total, verified, blocked, language, etc.
await svc.GetNesUserStats()    # total + top-5 lists: countries, cities, programs, industries
await svc.GetActivityStats()   # message counts + top-5 active users
await svc.GetMatchingStats()   # opted_out, total_rounds, last_round_date, last_round_assignments

# Full table dumps (for xlsx export)
await svc.GetAllTgUsers()      # list[TgUser]
await svc.GetAllNesUsers()     # list[NesUser]
await svc.GetAllMessages()     # list[Message]
```

### Admin Store (`core/configs/admin_store.py`)

DB-backed admin management — admins are stored in `TgUser.is_admin`:

```python
from nespresso.core.configs.admin_store import GetAdminIds, IsAdmin, AddAdmin, RemoveAdmin

ids = await GetAdminIds()          # list[int] — all chat_ids with is_admin=True
ok  = await IsAdmin(chat_id)       # bool
added   = await AddAdmin(chat_id)  # bool — False if already admin
removed = await RemoveAdmin(chat_id)  # bool — False if not admin
```

Initial admin IDs are seeded by `EnsureDB()` from `data/admins/admins.json` (if it exists) or from `_DEFAULT_ADMIN_IDS = [749410326]`.

### Repository Pattern

Each repo receives an `async_sessionmaker[AsyncSession]` and exposes typed async methods. All SQL lives here.

```
TgUserRepository methods:
  - CreateTgUser(chat_id)         → sets is_admin=True if chat_id in _DEFAULT_ADMIN_IDS
  - GetTgUser(chat_id, column=None)       → TgUser | T | None
  - GetTgUsersOnCondition(condition, column=None)
  - GetChatIdBy(tg_username=...|nes_id=...|nes_email=...)
  - UpdateTgUser(chat_id, column, value)

MatchRepository methods:
  - CreateRound(triggered_by)             → MatchRound
  - GetLastRound()                        → MatchRound | None
  - CreateAssignments(round_id, pairs)    → list[MatchAssignment]
  - GetAssignmentsByRound(round_id)       → list[MatchAssignment]
  - GetRecentExcludedPairs(last_n_rounds) → set[tuple[int, int]]
  - UpsertFeedback(assignment_id, response)

AnalyticsRepository methods:
  - GetTgUserStats()       → dict
  - GetNesUserStats()      → dict
  - GetActivityStats()     → dict
  - GetMatchingStats()     → dict
  - GetAllTgUsers/NesUsers/Messages()  → list[Model]
```

---

## Recommendation System Details

### Matching Algorithm (`recsys/matching/assign.py`)

**Entry point:** `RunMatching(triggered_by)` in `schedule.py` → `MatchingPipeline(triggered_by)` in `assign.py`.

**Algorithm:**
1. Filter eligible pool: `verified=True AND blocked=False AND matching_paused=False AND nes_id IS NOT NULL`
2. Fetch excluded pairs from last 2 rounds (history)
3. **Round 1:** Rejection-sample a derangement avoiding excluded pairs (up to 2000 attempts); fall back to ignoring history if exhausted
4. **Round 2** (if ≥3 users): another derangement excluding round-1 pairs as well
5. Result: each user gets 1 assignment (always) + 1 more if round 2 succeeds → **≤2 per user, directed/asymmetric**
6. Save `MatchRound` + flat list of `MatchAssignment` rows to DB
7. Send each user their profile list via i18n'd message (`matching.intro`), rate-limited at 30/sec

The matching is **asymmetric**: if user A is assigned to meet B, B is not necessarily assigned to meet A.

### OpenSearch Index Schema

Index name: `nes_users`

Each document has 4 fields per "side" (`mynes` = alumni self-description, `cv` = CV/work info):
- `{side}_text` — analyzed text for BM25
- `{side}_embedding` — 768-dim `knn_vector` for ANN search

### Hybrid Search Pipeline

Results are ranked via OpenSearch's normalization pipeline (`nespresso_normalization_pipeline`):
- **Normalization:** min-max per sub-query
- **Combination:** arithmetic mean with equal weights (0.25 each for 4 sub-queries)
- Sub-queries: `mynes_text` (BM25), `cv_text` (BM25), `mynes_embedding` (KNN), `cv_embedding` (KNN)
- BM25 queries are boosted by `ExtractKeywords(text)` extracted keywords
- Results below score threshold `0.1` are filtered out

`EnsureSearchPipeline()` (called at startup) creates this pipeline if it doesn't exist.

### `ScrollingSearch` (search.py)

Stateful pagination class. Cached in `SEARCHES: TTLCache` (5000 entries, 60-min TTL), keyed by `uuid.UUID`.

```python
search = ScrollingSearch(exclude_nes_id=current_user_nes_id)
pages = await search.HybridSearch(message)   # initial search, returns list[Page]
page  = await search.ScrollForward()         # next page
page  = await search.ScrollBackward()        # previous page
can_fwd = search.CanScrollFurtherForward()   # bool
can_bwd = search.CanScrollFurtherBackward()  # bool
```

**`Page` dataclass:** `scroll_id, score, number, profile, final_text` — lazy-formatted via `GetFormattedText()`.

---

## Internationalization

All user-facing strings live in `translations/en.json` and `translations/ru.json`.

```python
from nespresso.bot.lib.message.i18n import t, t_user

# Direct usage (lang already known)
text = t(lang, "key.path", name="Alice")

# Convenience wrapper (fetches lang from DB automatically)
text = await t_user(chat_id, "key.path", name="Alice")
```

- `lang` comes from `TgUser.language`
- Template substitution with `**kwargs` via Python `.format()`
- Falls back gracefully if key missing (falls back to English)
- `GetUserLanguageOrNone(chat_id)` → returns `None` if language not set or invalid

**Key namespaces:** `language.*`, `start.*`, `hub.*`, `settings.*`, `help.*`, `find.*`, `admin.*`, `matching.*`, `about.*`, `common.*`, `zero.*`

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

All secret fields (`TELEGRAM_BOT_TOKEN`, `EMAIL_ADDRESS`, `EMAIL_PASSWORD`) are `SecretStr`.

### Filesystem Paths (`core/configs/paths.py`)

`EnsurePaths()` is called at startup, creates required directories, and raises `FileNotFoundError` if `.env` is missing:
```
data/
  logs/bot/bot.log
  logs/api/api.log
  temp/
  recsys/embedding/model/   ← HuggingFace model cache
  recsys/opensearch/data/
```

`data/admins/admins.json` — optional seed file read by `EnsureDB()` to populate initial admin `is_admin` flags. Not managed at runtime.

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
1. EnsurePaths()              # Create required dirs/files, validate .env present
2. LoggerStart(LoggerSetup)   # Configure structured logging
3. EnsureDependencies():
   a. EnsureDB()              # Create PG tables if missing; ALTER TABLE for newer columns;
                              #   seed admin is_admin flags from admins.json or defaults
   b. EnsureOpenSearchIndex() # Create OS index if missing
   c. EnsureSearchPipeline()  # Create normalization pipeline if missing
4. SetExceptionHandlers()     # Asyncio + Aiogram error handlers
5. TestEmail()                # Verify SMTP credentials on startup, log warning if failed
6. dp.start_polling(bot, drop_pending_updates=True)

OnStartup() [registered as dp.startup hook]:
1. SetMenu()                  # Register /start, /cancel bot commands
2. RegisterHandlerCancel(dp)  # /cancel handler
3. RegisterAdminHandlers(dp)  # Admin panel routers
4. RegisterClientHandlers(dp) # Hub, start, find, about, settings routers
5. RegisterHandlerZeroMessage(dp)  # Fallback handler
6. SetBotMiddleware(dp)       # Logging + block-check middleware
7. NotifyOnStartup()          # Send "Bot started" to all admins
8. ProcessPendingUpdates()    # Handle messages received while offline

OnShutdown() [registered as dp.shutdown hook]:
1. NotifyOnShutdown()         # Send bot.log to all admins
2. CloseOpenSearchClient()    # Graceful OpenSearch disconnect
3. LoggerShutdown()           # Flush logs
```

Note: **No APScheduler** — there is no automatic matching job. Matching is triggered manually by admins.

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
from nespresso.bot.lib.message.io import SendMessage, SendDocument, PersonalMsg

await SendMessage(chat_id=chat_id, text=text, reply_markup=kb)
await SendDocument(chat_id=chat_id, document=file, caption=text)

# Bulk send (rate-limited 30/sec)
await SendMessagesToGroup([PersonalMsg(chat_id=id, text=t) for id, t in pairs])
```

`SendMessage` and `SendDocument` both catch `TelegramForbiddenError` (bot blocked by user) and call `UserBlockedBot(chat_id)` which unverifies the user and removes them from OpenSearch.

### Callback Handling

```python
from nespresso.bot.lib.message.io import ReceiveCallback

@router.callback_query(MyCallback.filter())
async def handle(query: CallbackQuery, callback_data: MyCallback):
    await ReceiveCallback(query, data=callback_data.action)
    ...
```

`ReceiveCallback` registers the user if new and logs the callback interaction.

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
- **Alembic** is listed as a dependency but no migration files exist yet; schema is created via `EnsureDB()` (`metadata.create_all` + explicit `ALTER TABLE IF NOT EXISTS` for columns added to existing tables).
- The ML model (Alibaba GTE) is downloaded on first run to `data/recsys/embedding/model/` — ensure write permissions and network access.
- OpenSearch requires the `OPENSEARCH_INITIAL_ADMIN_PASSWORD` env var; TLS is disabled in dev config.
- Rate limiting for broadcasts uses `AsyncLimiter(30, 1)` — 30 messages per second — to stay within Telegram API limits.
- `HUB_MESSAGES` is an in-memory cache; `TgUser.panel_message_id` is the persistent DB-backed counterpart used to restore hub state after bot restarts.
- **Matching feedback analytics** (`GetMatchingStats()`) reports opted-out count, total rounds, last round date, and last round assignments, but no per-response breakdown UI exists yet.
- **Statistics panel** sends stats as new separate messages (not hub edits) to avoid Telegram's 4096-char message length limit.
- **DB export** (`⬇️ Download DB`) opens a sub-panel with one button per table; each writes a temporary single-sheet `.xlsx` to `data/temp/` via `openpyxl`, sends it, then deletes it. The `message` table can be large — export time scales with row count.
- **User bio (about) indexing**: when a user saves their bio, `UpsertAboutOpenSearch(nes_id, about_text)` is called — it extracts keywords via KeyBERT, enriches the text, and upserts to the `cv` side of the OpenSearch document.
- **Help requests**: users can request help via Settings → Help → "Ask for help"; this silently notifies all admins with the user's `@username` and `chat_id`.

---

## Glossary

| Term | Meaning |
|------|---------|
| `chat_id` | Telegram user/chat identifier (BigInteger) |
| `nes_id` | NES alumni database ID |
| `verified` | User completed full registration flow |
| `is_admin` | DB column (TgUser) granting admin panel access |
| `matching_paused` | User opted out of matching rounds via Settings toggle |
| `mynes` | NES alumni self-description side in OpenSearch |
| `cv` | CV/work experience side in OpenSearch (also stores bio/about keywords) |
| `ScrollingSearch` | Stateful paginated search session |
| `UserContextService` | Unified service facade used by handlers |
| `AdminStore` | DB-backed admin management (`TgUser.is_admin`); functions: `GetAdminIds`, `IsAdmin`, `AddAdmin`, `RemoveAdmin` |
| `derangement` | Permutation where no element maps to itself (used in matching) |
| `MatchRound` | DB record of a single admin-triggered matching run |
| `MatchAssignment` | A single directed `(assigner → assigned)` pair within a round |
| `MatchFeedback` | User's response to a feedback request for a given assignment |
| `FeedbackResponse` | Enum: `"met"` / `"not_met"` / `"planning"` |
| `panel_message_id` | DB-persisted hub message ID; enables hub deletion across bot restarts |
| `HUB_MESSAGES` | In-memory `dict[chat_id → message_id]` for fast hub message tracking |
| `AnalyticsService` | Dedicated service for admin stats queries and full-table DB exports |
| `StatisticsAction` | Enum of statistics sub-panel actions (Users, Alumni, Activity, Matching, DownloadDB) |
| `EnsureSearchPipeline` | Creates OpenSearch normalization pipeline for hybrid BM25+KNN search |
| `PersonalMsg` | Dataclass `(chat_id, text)` used with `SendMessagesToGroup` for bulk sends |
| `DocSide` | Enum: `mynes` or `cv` — which side of the OpenSearch document to upsert |
