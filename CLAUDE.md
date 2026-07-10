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
| Query understanding | Anthropic Claude Haiku 4.5 (parser: moderation + semantic + expansion + filters; reranker; index-time enrichment — all temperature 0, fallback-safe, prompt-cached) |
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
│   │   ├── admin_ids.py     # DEFAULT_ADMIN_IDS — built-in chat_ids that are
│   │   │                    #   always admins (cannot be removed). Pure data, no imports.
│   │   └── title_store.py   # JSON-backed hub title overrides (GetTitle, SetTitle, GetBothTitles)
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
│   │   ├── nes_user.py      # NesUser model (alumni profile) + PROGRAMS vocab dict
│   │   ├── message.py       # Message model (audit log)
│   │   ├── match.py         # MatchRound, MatchAssignment, MatchFeedback models
│   │   ├── profile_reaction.py # ProfileReaction model (per-user like/dislike + hide) + ReactionKind
│   │   └── schemas/
│   │       └── nes_user.py  # Pydantic schema for NesUser API response
│   ├── repositories/        # Repository pattern (pure DB access)
│   │   ├── tg_user.py
│   │   ├── nes_user.py
│   │   ├── message.py
│   │   ├── match.py         # MatchRepository
│   │   ├── profile_reaction.py # ProfileReactionRepository (reactions + hidden profiles)
│   │   ├── analytics.py     # AnalyticsRepository — aggregation queries for admin stats
│   │   └── checking.py      # CheckColumnBelongsToModel(), CheckOnlyOneArgProvided()
│   ├── services/            # Business logic over repos
│   │   ├── user.py          # UserService (TgUser + NesUser + GetAdminChatIds)
│   │   ├── message.py       # MessageService
│   │   ├── matching.py      # MatchingService (match rounds + assignments + feedback)
│   │   ├── profile_reaction.py # ProfileReactionService (reactions + hidden profiles)
│   │   ├── admin.py         # DB-backed admin store (GetAdminIds, IsAdmin, AddAdmin, RemoveAdmin)
│   │   ├── user_context.py  # UserContextService (unified facade)
│   │   └── analytics.py     # AnalyticsService + GetAnalyticsService()
│   └── session.py           # Async engine, session factory, EnsureDB()
├── bot/                     # Telegram bot
│   ├── lifecycle/
│   │   ├── creator.py       # Bot + Dispatcher + BOT_ID singletons
│   │   ├── menu.py          # SetMenu() — register /start, /cancel commands
│   │   └── sync_scheduler.py # StartSyncScheduler()/StopSyncScheduler() — hourly
│   │                        #   asyncio loop driving api/sync.SyncFromMyNES()
│   ├── handlers/
│   │   ├── client/
│   │   │   ├── hub_view.py     # LEAF: SendHub(), HubKeyboard(), HubCallbackData/HubAction
│   │   │   │                   #   (extracted from hub.py to break an import cycle)
│   │   │   ├── commands/
│   │   │   │   ├── hub.py      # Hub router + callback handlers (builders live in hub_view.py)
│   │   │   │   ├── start.py    # Registration FSM (blocks completion until alum is listed)
│   │   │   │   ├── about.py    # About panel: view/edit user bio (hub sub-panel + FSM)
│   │   │   │   ├── find.py     # Search FSM (2 states + pagination + per-result actions panel)
│   │   │   │   └── settings.py # Settings sub-panel (matching toggle, language, help,
│   │   │   │                   #   "My data & privacy": hidden profiles, export, delete account)
│   │   │   ├── email/
│   │   │   │   └── verification.py  # CreateCode(), SendCode(), TestEmail()
│   │   │   └── register.py  # RegisterClientHandlers()
│   │   ├── admin/
│   │   │   ├── commands/
│   │   │   │   ├── admin.py     # Main panel + all action handlers
│   │   │   │   ├── back.py      # BackToAdminPanelCallbackData, BackToHubCallbackData
│   │   │   │   ├── blocking.py  # Block/unblock users sub-panel
│   │   │   │   ├── admins.py    # Admin list management sub-panel (notifies other admins on changes)
│   │   │   │   ├── matching.py  # Run matching + Demo dry-run + send feedback request sub-panel
│   │   │   │   ├── statistics.py # Statistics sub-panel + DB export
│   │   │   │   ├── title.py     # Edit per-language hub title sub-panel
│   │   │   │   ├── mynes.py     # MyNES sub-panel: manual "Sync now" + last-sync report
│   │   │   │   └── logs.py      # Logs sub-panel: quick/debug log download (ShowLogsPanel)
│   │   │   └── register.py      # RegisterAdminHandlers()
│   │   ├── common/
│   │   │   ├── commands/
│   │   │   │   ├── cancel.py    # /cancel clears FSM state
│   │   │   │   └── zero.py      # Fallback for unrecognized input
│   │   │   └── register.py      # RegisterHandlerCancel(), RegisterHandlerZeroMessage()
│   └── lib/
│       ├── hub_state.py     # HUB_MESSAGES + HUB_LOCKS: in-memory hub-message cache
│       ├── message/
│       │   ├── io.py        # SendMessage, SendDocument, EditMessage, EditPanel,
│       │   │                #   SendMessagesToGroup, ReceiveMessage, ReceiveCallback, PersonalMsg
│       │   ├── i18n.py      # t(), t_user(), GetUserLanguage(), GetUserLanguageOrNone(),
│       │   │                #   SetUserLanguage()
│       │   ├── checks.py    # CheckVerified(), IsUnshared() (directory-sharing gate)
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
│   │   ├── llm/             # Claude-powered query understanding (Haiku 4.5, temperature 0)
│   │   │   ├── client.py    # AsyncAnthropic singleton + CloseLLMClient()
│   │   │   ├── world_knowledge.py # INDUSTRY_TAXONOMY (source of truth) → WORLD_KNOWLEDGE
│   │   │   │                 #   (query side) + DIRECTORY_KNOWLEDGE (index/enrich side)
│   │   │   ├── query_understanding.py # ParseQuery() → is_valid_search (moderation) +
│   │   │   │                 #   semantic_query + expanded_terms + filters; adaptive 1h
│   │   │   │                 #   prompt caching + deterministic slur backstop
│   │   │   ├── rerank.py    # Rerank() — compact ids-only reranker (fallback-safe)
│   │   │   ├── enrich.py    # EnrichTexts() — index-time inline world-knowledge annotation
│   │   │   └── alerts.py    # ReportLLMError()/IsCreditsExhausted()/SetAdminAlertHook() —
│   │   │                    #   throttled out-of-credits admin alert (recsys→bot via hook)
│   │   ├── client.py        # AsyncOpenSearch client + CloseOpenSearchClient()
│   │   ├── index.py         # Unified index schema (text + embedding + f_*) + EnsureOpenSearchIndex(),
│   │   │                    #   DocAttr; drops+recreates a legacy two-sided index
│   │   ├── filtering.py     # StructuredFields(), StructuredBoost(), CandidateCard() (structured pool)
│   │   ├── search_pipeline.py # EnsureSearchPipeline() — normalization pipeline for hybrid search
│   │   ├── document.py      # BuildProfileText(), UpsertProfileOpenSearch(),
│   │   │                    #   BulkUpsertProfilesOpenSearch(), DeleteUserOpenSearch(), PresentDocIds()
│   │   ├── profile_write.py # RebuildProfileForBio() — interactive one-profile re-index on bio save
│   │   └── search.py        # ScrollingSearch: parser→2-pool retrieve→re-score→rerank, lazy paging
│   └── matching/
│       ├── assign.py        # MatchUsers(), CreateMatching(), DemoMatching(), SendMatchingInfo(),
│       │                    #   MatchingPipeline() — core matching logic
│       ├── schedule.py      # RunMatching(triggered_by) — thin entry point (no scheduler)
│       └── emoji.py         # RandomEmoji() for match identity
├── api/
│   ├── app.py               # FastAPI app + lifespan
│   ├── request.py           # FetchUsersList() [GET /user/list], GetNesUserFromMyNES()
│   │                        #   [GET /user/byEmail], ResolveNesUserByEmail() (DB-first
│   │                        #   + byEmail fallback). NO data-sharing-permission calls.
│   ├── sync.py              # SyncFromMyNES() — hourly directory mirror (DB + OpenSearch),
│   │                        #   SyncReport, LAST_SYNC
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

db/services/admin ←── bot/lib (filters, checks), db/session (seeding on startup)

core/configs ←── everywhere (settings, paths, admin_ids, title_store)
```

### Key Dependency Rules

- **Handlers** never import repos directly — always go through `UserContextService` or `AnalyticsService`.
- **Repos** contain only SQL — no business logic, no Telegram calls.
- **Services** wrap repos; `UserContextService` is the single entry point for handlers; `AnalyticsService` is the dedicated entry point for analytics/export queries.
- **`recsys/`** imports from `db/` for user data, and is *mostly* free of `bot/` — with two deliberate exceptions: `recsys/matching/assign.py` imports `bot.lib.message.{i18n,io}` (it DMs each matched user their i18n'd assignments) and `recsys/profile.py` imports `bot.lib.chat.username` (the username helper). The LLM layer stays clean via a hook: `recsys/searching/llm/alerts.py` reaches `bot` only through the injected `SetAdminAlertHook`.
- **`bot/lib/message/io.py`** is the only place that calls Aiogram's send/edit methods (`SendMessage`, `SendDocument`, `EditMessage`, `EditPanel`) — except inline markups built in handlers.
- **`core/`** has no imports from other nespresso modules — only stdlib + third-party (the DB-backed admin store moved to `db/services/admin.py` to keep this true; only `DEFAULT_ADMIN_IDS`, pure data, stays in `core/configs/admin_ids.py`).
- **Admin handlers** all live under `bot/handlers/admin/commands/`; the main panel + broadcast/DM/messages actions are in `admin.py`, and each sub-panel (blocking, admins, matching, statistics, title, mynes, logs) has its own module.

---

## Data Models

### `TgUser` — Telegram identity
| Column | Type | Notes |
|--------|------|-------|
| `chat_id` | BigInteger PK | Telegram chat ID |
| `nes_id` | BigInteger | NES profile link, indexed, nullable. **Plain column, NOT a DB foreign key** — deleting a NesUser row does not cascade. |
| `nes_email` | String | indexed |
| `username` | String | Telegram @handle, indexed |
| `language` | String | "en" or "ru" |
| `about` | String | Free-form bio |
| `panel_message_id` | BigInteger | Last active hub message ID (for single-instance hub) |
| `verified` | Boolean | Registration complete |
| `blocked` | Boolean | Admin-blocked |
| `matching_paused` | Boolean | User opted out of matching rounds (default False) |
| `is_admin` | Boolean | Admin privileges (default False) |
| `created_at` | DateTime | Server default CURRENT_TIMESTAMP |
| `updated_at` | DateTime | Server default CURRENT_TIMESTAMP |

### `NesUser` — Alumni profile (mirrored from the MyNES directory)
| Column | Type | Notes |
|--------|------|-------|
| `nes_id` | BigInteger PK | |
| `nes_email` | String | indexed. The directory feed now carries `email`, so the sync writes it — but COALESCE-guarded (`SyncUpsertNesUsers`), so a feed that ever drops email can't NULL an email bound at registration (byEmail path). |
| `name` | String | |
| `sex` | String | `"MALE"` / `"FEMALE"`, from the feed. Indexed as `f_sex`; drives gender filtering (boost-only, not recall). |
| `city/region/country` | String | |
| `programs` | JSON array | `[{name, year}]` from the feed — NES program(s) + class year. Indexed as multi-valued `f_program` / `f_class_year`. |
| `program/class_name` | String | Primary (latest) program name + year, **derived** from `programs` for display/analytics. |
| `hobbies/industry_expertise/country_expertise/professional_expertise` | JSON array | Skills/interests |
| `main_work/additional_work` | JSON object | Employment |
| `pre_nes_education/post_nes_education` | JSON array | Education history |
| `listed` | Boolean | In the MyNES directory (`Show in a class' directory`). Sync sets False + drops the OpenSearch doc when a user disappears. Default True. Also gates bot access (`checks.IsUnshared`) and matching (`CreateMatching` filters on `listed`). |
| `mynes_text_hash` | String | sha256 over the raw feed JSON + the user's bio + a doc-version tag; lets sync skip re-embedding unchanged profiles. |
| `mynes_text/about_text/enriched_text` | String | Persisted retrieval texts (visible in the admin DB export): raw directory `SearchText`, raw bio at last sync, and the final enriched text embedded into OpenSearch. |
| `synced_at` | DateTime | Last directory refresh. |

**Key methods on `NesUser`:**
- `SelfDescription()` — name, location, program/class (card header, HTML)
- `WorkDescription()` — employment + post-NES education (card body, HTML)
- `SearchText()` — role-framed profile text (`Label: value` lines) used, after enrichment, for OpenSearch indexing
- **`PROGRAMS`** (module dict) — canonical NES program vocabulary (full feed name → short name). Single source of truth: the query parser derives its program-filter list from `list(PROGRAMS)`, so the two can't drift.

### `Message` — Audit log
Stores every bot↔user message exchange with timestamp and side (`Bot`/`User` enum via `MessageSide`).

| Column | Type | Notes |
|--------|------|-------|
| `chat_id` | BigInteger | Part of composite PK (Telegram message_id is unique only within a chat) |
| `message_id` | BigInteger | Part of composite PK |
| `side` | Enum(MessageSide) | `bot` or `user` |
| `text` | String | message text or caption |
| `time` | DateTime | Server default CURRENT_TIMESTAMP |

`AddMessage` uses `INSERT … ON CONFLICT DO NOTHING` so redelivered Telegram updates are idempotent.

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

### `ProfileReaction` — Per-user reaction + hide on an alumni profile

One row per `(rater, target)` a searcher interacted with in Find. Distinct from the admin `TgUser.blocked` (which bars a whole user from the bot): here a normal user privately rates/hides an individual profile in their **own** results. Unique on `(rater_chat_id, target_nes_id)`; all writes are atomic upserts.

| Column | Type | Notes |
|--------|------|-------|
| `id` | Integer PK | Auto-increment |
| `rater_chat_id` | BigInteger | The reacting user's chat_id, indexed |
| `target_nes_id` | BigInteger | The reacted-to alumni profile's nes_id, indexed |
| `reaction` | String | `"like"` / `"dislike"` / NULL (see `ReactionKind`). **Analytics-only signal — does NOT affect retrieval or ranking.** |
| `blocked` | Boolean | True ⇒ profile hidden from the rater's Find results + matching. Default False |
| `created_at`/`updated_at` | DateTime | |

---

## Core Flows

### 1. User Registration (`/start`)

```
/start
  └─ if no language set → state: ChooseLanguage → reply keyboard EN/RU → SetUserLanguage()
  └─ if already verified → SendHub(chat_id) immediately
  └─ state: EmailGet        → (asked straight after language/start — no phone step)
                              free-text email input (lowercased; must end with @nes.ru;
                              cooldown after 3 wrong codes; rejects emails already
                              owned by a verified user)
                              → ResolveNesUserByEmail(email): DB-first lookup in the
                                synced nes_user table, falling back to ONE
                                GET /user/byEmail call. Only if a real alumnus is
                                found do we CreateCode() → SendCode() and stash the
                                resolved nes_id in FSM state. (No data-sharing call.)
  └─ state: EmailConfirm    → user enters 6-digit code → validate (3 attempts then
                              cooldown to EmailGet). On success: assign the FSM-stashed
                              nes_id to the TgUser — NO MyNES API call here.
                              GATE: completion is blocked unless the linked NesUser is
                              LISTED (in the directory). A real alum whose profile is
                              unlisted (row missing / listed=False) can verify their code
                              but is told to enable "Show in a class' directory" — re-
                              entering the code once the sync reflects listed=True finishes.
                              A correct code + listed profile completes registration:
                              verified = True (NO terms-of-use step).
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
        └─ sub-panels (Blocking, Admins, Matching, Statistics, Title) edit same message
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
       │       ├─ "✉️ Ask for help" → notifies ALL admins (5-min per-user cooldown;
       │       │                       shared by the button and the /help path)
       │       └─ "⬅️ Back"        → edits hub message back to Settings sub-panel
       ├─ "🔒 My data & privacy" → edits hub message to Privacy sub-panel
       │   ├─ "🙈 Hidden profiles" → paginated manager of profiles the user hid in Find,
       │   │                         each with an "Unblock" button
       │   ├─ "⬇️ Export my data"  → sends a single-user xlsx (account + messages +
       │   │                         reactions + match assignments/feedback)
       │   ├─ "🗑 Delete my account" → confirm step → cascade-deletes all DB rows
       │   │                         (DeleteAccountData) + drops the OpenSearch doc
       │   └─ "⬅️ Back"            → edits hub message back to Settings sub-panel
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
       │      → RebuildProfileForBio(nes_id, about) rebuilds the ONE unified doc
       │        (SearchText + bio → enrich → embed → full-replace write)
       │      → state cleared → SendHub (fresh hub message)
       └─ "⬅️ Back" → edits hub message back to HubKeyboard
```

### 5. Alumni Search (hub button)

```
Find
  └─ state: Text   → user enters query text
                     Gates BEFORE any paid work: 3s per-user cooldown, then a
                       60-searches/user/day cap (_DAILY_SEARCH_LIMIT, per UTC day),
                       then a token-length check. Only a committed search is counted.
                     ParseQuery(text)  [Claude Haiku, temperature 0, fallback-safe]
                       → is_valid_search : moderation gate. False (slur / sexual /
                         non-bona-fide like "плохой человек") ⇒ HybridSearch returns
                         None ⇒ user sees a plain "Ничего не найдено" (find.not_found).
                       → semantic_query  : cleaned intent → embedding + BM25
                       → expanded_terms  : world-knowledge expansion (RU+EN), fed to a
                         low-boost (0.25) BM25 channel; gated by QUERY_EXPANSION_ENABLED
                       → filters         : structured constraints (program, city, company,
                         role, university, industry/professional/country expertise …)
                     Two-pool retrieve: hybrid semantic pool (BM25 + KNN on the ONE
                       unified `text`/`embedding` field) + structured pool (terms/match
                       on f_* fields for filter-led queries). Profiles the user hid are
                       excluded via the ScrollingSearch blocked-nes-id set.
                     Re-score: STRUCT_WEIGHT * StructuredBoost + base hybrid score
                     Rerank(text, top-30) [Claude Haiku, temperature 0] — anchors precision
                       on the RAW query, so query expansion can widen recall safely
                     ScrollingSearch cached in SEARCHES TTLCache (5000 entries, 60 min)
                     Zero results keep the user in state Text with a "try another" nudge
                       (find.try_another) instead of dumping them back to idle.
  └─ state: Forward → paginate with prev/next inline buttons (lazy 30-per-chunk; "N+")
                      display NesUser profile for each result.
                      Each card has a "•••" actions panel (swaps only the keyboard):
                        👍/👎 like/dislike (toggle; analytics-only, no ranking effect),
                        🚫 hide (blocks the profile for this user, then advances), Back.
```

### 6. Manual Matching (admin-triggered)

There is **no automatic scheduler**. An admin must manually trigger each round.

```
Admin → Matching panel → "▶️ Run Matching Now"
  └─ Guards: a hard concurrency lock (MatchingInProgressError) + a 10-min cooldown
     since the last round (MatchingCooldownError) — repeated taps can't blast DMs.
  └─ Notify all OTHER admins: "X started a matching round"
  └─ Filter eligible users: verified=True, blocked=False, matching_paused=False,
     AND the linked NesUser is listed (delisted users are excluded)
  └─ Excluded pairs = last-2-rounds history PLUS every per-user hidden-profile block,
     added BOTH directions (a one-sided hide never gets force-matched)
  └─ MatchUsers():
       Round 1: derangement avoiding excluded pairs → everyone gets ≥1 assignment
       Round 2: second derangement (if ≥3 users) avoiding round-1 pairs + excluded
       Result: each user gets 1 or 2 directed assignments (asymmetric)
  └─ Save MatchRound + all MatchAssignments to DB
  └─ Send each user their assigned profiles (i18n, rate-limited 30/sec)
  └─ Report count to admin

Admin → Matching panel → "🧪 Demo" (dry run)
  └─ DemoMatching(): same eligible pool + exclusions as a real round, but saves NO
     MatchRound and notifies NO user — sends the admin an xlsx of the would-be pairs.
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

Requires `TgUser.is_admin = True` in DB (checked via `IsAdmin(chat_id)` from `db/services/admin`).

Accessed via Hub → "Admin panel" button (edits hub message in-place).

Actions: Logs (sub-panel) | View user messages | Send DM | Broadcast | Block/Unblock | Run Matching / Demo / Send Feedback | Manage admins | Statistics | Title | MyNES (sync)

- **Send DM / View messages** accept EITHER a Telegram `@username` OR a NES email as the target (resolved via `_ResolveAdminTarget`: an `@` that survives stripping the leading sigil marks an email, looked up by `nes_email`).
- **Broadcast** (Send All) now stages a confirmation: it stashes the text, shows the recipient count + Confirm/Cancel, and only an explicit Confirm fans out (the buttons are dropped so a second tap can't re-fire it).

**Admin gating:** `RegisterAdminHandlers()` applies `AdminFilter` to every admin router (both `.message` and `.callback_query`), so non-admins cannot trigger admin handlers even if they reverse-engineer the callback data prefixes. (The matching `feedback_router` is registered under `RegisterClientHandlers` WITHOUT `AdminFilter`, since its buttons are DMed to ordinary matched alumni.)

**Admin change notifications:** When an admin adds or removes another admin, all other admins receive a notification with who performed the action and who was affected.

### 8a. Title Sub-panel (admin sub-panel)

The hub's title text per language is editable at runtime:

```
Admin Panel → 🏷️ Title → edits hub message to Title sub-panel
  ├─ ✏️ Edit EN → state: TitlePanelStates.EditEN → admin types new EN title → SetTitle("en", ...)
  └─ ✏️ Edit RU → state: TitlePanelStates.EditRU → admin types new RU title → SetTitle("ru", ...)
```

Titles are persisted in `data/title/title.json` via `core/configs/title_store.py`. `GetTitle(lang)` falls back to a built-in default if the file is missing or unreadable.

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
  ├─ 🤝 Matching → eligible users (same `listed` filter the matcher uses), opted-out
  │                count, total rounds, last round date/assignments, PLUS a feedback
  │                breakdown (met / not_met / planning + response rate via GetFeedbackStats)
  └─ ⬇️ Download DB → edits hub to Download DB sub-panel (Back → Statistics)
       ├─ 👤 tg_user  → sends tg_user.xlsx
       ├─ 🎓 nes_user → sends nes_user.xlsx
       └─ 💬 message  → sends message.xlsx
```

### 10. MyNES Sub-panel (admin sub-panel)

```
Admin Panel → 🔄 MyNES → edits hub message to MyNES sub-panel
  ├─ header shows the last completed sync (status, when, fetched/alumni/upserted/
  │  reindexed/deferred/delisted/errors/seconds)
  └─ "▶️ Sync now" → runs SyncFromMyNES("admin:<chat_id>") on demand (busy no-op if
                     one is already running), then refreshes the panel header
```

### 11. Directory-Sharing Enforcement Gate

A verified user whose linked `NesUser` is unlisted (`listed=False` — they turned off
"Show in a class' directory" and the hourly sync delisted them) is **paused** from
using the bot until they re-share. `checks.IsUnshared(chat_id)` is enforced in BOTH
middlewares (message + callback) and reads `listed` live, so a re-list auto-lifts the
gate on the next sync with no stored flag and no re-registration. Admins and
not-yet-verified users are never caught (registration is gated separately at the
confirm step — see Flow 1).

---

## Service Layer Details

### `UserContextService`

The **central facade** used by all handlers. Combines `UserService`, `MessageService`, `MatchingService`, and `ProfileReactionService` via multiple inheritance.

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
await ctx.CreateRoundWithAssignments(triggered_by, [(a, b), ...])  # → (MatchRound, list[MatchAssignment]), one transaction
await ctx.GetLastRound()                               # → MatchRound | None
await ctx.MarkFeedbackSent(round_id)                   # stamps MatchRound.feedback_sent_at
await ctx.GetAssignmentsByRound(round_id)              # → list[MatchAssignment]
await ctx.GetAssignment(assignment_id)                 # → MatchAssignment | None
await ctx.GetRecentExcludedPairs(last_n_rounds=2)      # → set[tuple[int, int]]
await ctx.UpsertFeedback(assignment_id, response)      # atomic INSERT ... ON CONFLICT

# Profile reactions / hidden profiles (per-user)
await ctx.SetProfileReaction(rater_chat_id, target_nes_id, reaction)  # like/dislike/None
await ctx.SetProfileBlocked(rater_chat_id, target_nes_id, blocked)    # hide/unhide
await ctx.GetProfileReaction(rater_chat_id, target_nes_id)            # → str | None
await ctx.GetBlockedTargetNesIds(rater_chat_id)                       # → list[int] (Find exclude)
await ctx.GetBlockedChatIdPairs()                                     # → set[(rater, target)] (matching)

# Self-service privacy (GDPR)
await ctx.DeleteAccountData(chat_id, nes_id)  # cascade-delete all DB rows for this user
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

### Admin Store (`db/services/admin.py`)

DB-backed admin management — admins are stored in `TgUser.is_admin`. Moved here from `core/configs` (it reads/writes through the DB via `UserContextService`, so `core` no longer imports another nespresso module):

```python
from nespresso.db.services.admin import GetAdminIds, IsAdmin, AddAdmin, RemoveAdmin

ids = await GetAdminIds()          # list[int] — all chat_ids with is_admin=True
ok  = await IsAdmin(chat_id)       # bool
added   = await AddAdmin(chat_id)  # bool — False if already admin
removed = await RemoveAdmin(chat_id)  # bool — False if not admin
```

Initial admin IDs are seeded by `EnsureDB()` from `data/admins/admins.json` (if it exists) AND from `DEFAULT_ADMIN_IDS` declared in `core/configs/admin_ids.py`. Default-admin chat_ids cannot be removed via `RemoveAdmin()` and `IsAdmin()` short-circuits to `True` for them — they are guaranteed admins regardless of the DB.

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
  - CreateRoundWithAssignments(triggered_by, pairs) → (MatchRound, list[MatchAssignment]), one transaction
  - GetLastRound()                        → MatchRound | None
  - MarkFeedbackSent(round_id)
  - GetAssignmentsByRound(round_id)       → list[MatchAssignment]
  - GetAssignment(assignment_id)          → MatchAssignment | None
  - GetRecentExcludedPairs(last_n_rounds) → set[tuple[int, int]]
  - UpsertFeedback(assignment_id, response)  # atomic INSERT ... ON CONFLICT (assignment_id)

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
1. Filter eligible pool: `verified=True AND blocked=False AND matching_paused=False AND nes_id IN (listed nes_ids)` (the `listed` subquery also implies `nes_id IS NOT NULL`). `EligibleMatchingChatIds()` is the single accessor shared by the matcher and the stats panel.
2. Excluded pairs = last-2-rounds history PLUS every per-user hidden-profile block, added **both directions** (`_ExcludedPairsWithBlocks`)
3. **Round 1:** Rejection-sample a derangement avoiding excluded pairs (up to 2000 attempts); fall back to ignoring history if exhausted
4. **Round 2** (if ≥3 users): another derangement excluding round-1 pairs as well
5. Result: each user gets 1 assignment (always) + 1 more if round 2 succeeds → **≤2 per user, directed/asymmetric**
6. Save `MatchRound` + flat list of `MatchAssignment` rows to DB
7. Send each user their profile list via i18n'd message (`matching.intro`), rate-limited at 30/sec

`CreateMatching` is guarded by a concurrency lock (`MatchingInProgressError`) and a 10-minute cooldown since the last round (`MatchingCooldownError`). `DemoMatching()` runs the same computation over the same pool but persists nothing and notifies nobody (admin preview/export).

The matching is **asymmetric**: if user A is assigned to meet B, B is not necessarily assigned to meet A.

### OpenSearch Index Schema

Index name: `nes_users`

**One unified document per `nes_id`** (the old two-sided `mynes`/`cv` model is gone). OpenSearch is a pure projection of Postgres — every write is a full replace (`index`, not partial update), rebuilt from the DB:
- `text` — analyzed text for BM25 (directory `SearchText` + the user's bio, enriched)
- `embedding` — 768-dim `knn_vector` for ANN search (of that same `text`)
- structured `f_*` fields (`f_program`, `f_city`, `f_company`, …) in `_source` for the structured pool + rerank cards

`EnsureOpenSearchIndex()` detects a LEGACY two-sided mapping (`mynes_text`/`cv_text`) and **drops + recreates** the index unified (a full re-embed is unavoidable; the startup sync is blocking, so an empty-then-repopulated index is fine). `DocAttr.Field` names the `text`/`embedding` fields.

### Hybrid Search Pipeline

Results are ranked via OpenSearch's normalization pipeline (`nespresso_normalization_pipeline`):
- **Normalization:** min-max per sub-query
- **Combination:** arithmetic mean with weights `[0.5, 0.5]` over **2 sub-queries** (each doc now has exactly one populated `text`+`embedding`, so the old cv-side down-weighting is gone)
- Sub-queries: `text` (BM25) + `embedding` (KNN)
- The BM25 sub-query is a `bool/should` of: `semantic_query` (full weight) + `ExtractKeywords(semantic)` keywords (boost 0.5) + the parser's `expanded_terms` (boost 0.25)
- Results below score threshold `0.1` are filtered out

This hybrid (semantic) pool is unioned with a **structured pool** (`filtering.py`: `terms`/`match` over the indexed `f_*` fields) so filter-led queries with sparse semantic text (e.g. "кто работал в Сбербанке") still recall; candidates are then re-scored as `STRUCT_WEIGHT * StructuredBoost + base` and the top 30 reranked by `Rerank()`.

`EnsureSearchPipeline()` (called at startup) creates/updates this pipeline.

### `ScrollingSearch` (search.py)

Stateful pagination class. Cached in `SEARCHES: TTLCache` (5000 entries, 60-min TTL), keyed by `uuid.UUID`.

```python
search = ScrollingSearch(exclude_nes_id=current_user_nes_id, blocked_nes_ids=hidden_set)
pages = await search.HybridSearch(message)   # initial search, returns list[Page]
page  = await search.ScrollForward()         # next page
page  = await search.ScrollBackward()        # previous page
can_fwd = search.CanScrollFurtherForward()   # bool
can_bwd = search.CanScrollFurtherBackward()  # bool
```

**`Page` dataclass:** `number, profile, _body` — profile text lazy-formatted via `GetProfileText()`; the page counter (`n / loaded[+]`) is rendered live by `CurrentText()`. Pages are materialized lazily in 30-per-chunk windows (`_DISPLAY_LIMIT`) as the user scrolls; a trailing `+` ("N+") means more matching profiles can still be loaded.

### LLM Query Understanding & Reranking (`recsys/searching/llm/`)

All three calls use **Claude Haiku 4.5 at temperature 0** (deterministic, reproducible), are **fallback-safe** (any error/timeout degrades to the pre-LLM behaviour), and never block search. The shared taxonomy is generated from one source: `INDUSTRY_TAXONOMY` (in `world_knowledge.py`) renders both `WORLD_KNOWLEDGE` (query-side parser prompt) and `DIRECTORY_KNOWLEDGE` (index-side enrich prompt), so query and index speak one vocabulary by construction.

**`ParseQuery(text)` → `ParsedQuery`** (`query_understanding.py`)
- `is_valid_search` — **moderation gate**. `False` for slurs / sexual / abusive / non-bona-fide queries (incl. obfuscated & wrapped forms); the handler then returns a plain "nothing found" (`find.not_found`). Fail-open: only an explicit `False` blocks legitimate searches.
- `semantic_query` — cleaned intent (drives the embedding + BM25).
- `expanded_terms` — tight, category-only world-knowledge expansion (RU+EN, **no** employer names); fed to a 0.25-boost BM25 channel. Gated by `QUERY_EXPANSION_ENABLED` (eval-neutral; on by default).
- `filters` — MyNES controlled-vocabulary constraints. The `program` filter list is derived from `list(PROGRAMS)` (the `nes_user.py` vocab dict) so it can't drift from the indexed `f_program` values. `class_year` / `gender` are **forward-compatible**: extracted now, will light up when MyNES adds them to `/user/list`.
- **Adaptive prompt caching:** the ~4.2k-token system prompt clears Haiku 4.5's 4096-token cache floor. A 1-hour `cache_control` is attached only once the rolling 60-min query count reaches `PARSER_CACHE_HOURLY_THRESHOLD` (5) — below that it is sent uncached (a 1h write costs 2× base input and only amortizes at ≥3 queries/hour).
- **Deterministic backstop:** if the LLM call fails, a small high-precision slur regex still rejects the most egregious queries.

**`Rerank(query, candidates)`** (`rerank.py`) — reorders the top `RERANK_CANDIDATES` (30) best-first against the **raw** query (compact ids-only output). Anchoring precision on the raw query is what lets `expanded_terms` widen recall safely. Identity fallback on any failure.

**`EnrichTexts(texts)`** (`enrich.py`) — **index-time inline** world-knowledge annotation run during sync, before embedding: rewrites each profile with short parenthetical glosses inserted **beside the entity they explain** — `Яндекс (big tech, IT)`, `XTX Markets (HFT, algorithmic trading)`, `ВШЭ (strong CS school)` — in RU+EN, so a query for "HFT" matches an "XTX" profile. Keeping the world-knowledge as coherent natural language (not a trailing keyword bag) makes the single profile vector embedding-friendly while still carrying every term for BM25 — **one artifact, both channels**. The annotation is **additive**: a token-retention guard (≥90% of the original's significant tokens must survive) — an unfaithful output is retried with a small temperature and the best-retention result kept. Uses the shared `DIRECTORY_KNOWLEDGE` block (same `INDUSTRY_TAXONOMY` as the query side). Bounded concurrency (`ENRICH_CONCURRENCY`); only re-runs on profiles whose `mynes_text_hash` changed. Returns an `EnrichResult` per input with one of three dispositions: enriched (index it), `retry` (transient API error — index raw now, re-enrich next sync), or `skip` (out of credits — see below).

**Out-of-credits graceful degradation** (`alerts.py`) — when the org runs OUT OF Claude credits, every call 400s and the fallback-safe callers would silently degrade with no operator signal. `ReportLLMError()` / `IsCreditsExhausted()` classify that case and fire a **throttled** (≤1 per 30 min) admin alert via the `SetAdminAlertHook` injected at startup (`admin.NotifyOnLLMOutage`). Behaviour per caller: parser + reranker fall back to raw behaviour; **enrichment DEFERS** — a shared circuit breaker trips on the first credit failure, the affected profiles are left entirely untouched (no downgraded doc), the sync counts them as `SyncReport.deferred` and retries them next run once credits return, and the MyNES panel surfaces the "Deferred" count.

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

The hub welcome text is **not** in translations — it is fetched at render time from `title_store.GetTitle(lang)` so admins can change it without redeploying.

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

# Anthropic Claude — query understanding for Find search (all default to Haiku 4.5)
CLAUDE_API_KEY=                    # SecretStr
QUERY_PARSER_MODEL=               # default claude-haiku-4-5
QUERY_EXPANSION_ENABLED=          # default True — query-side world-knowledge expansion
PARSER_CACHE_HOURLY_THRESHOLD=    # default 5 — rolling 60-min query count to enable 1h prompt cache
RERANK_MODEL= / RERANK_ENABLED= / RERANK_CANDIDATES=   # default haiku-4-5 / True / 30
ENRICH_MODEL= / ENRICH_ENABLED= / ENRICH_CONCURRENCY=  # index-time enrichment (haiku-4-5 / True / 8)
LLM_TIMEOUT_SECONDS=              # default 8.0 (interactive parser/rerank)
ENRICH_TIMEOUT_SECONDS=          # default 60.0 (background enrichment)
MYNES_SYNC_INTERVAL_SECONDS=      # default 3600
```

All secret fields (`TELEGRAM_BOT_TOKEN`, `EMAIL_ADDRESS`, `EMAIL_PASSWORD`, `CLAUDE_API_KEY`) are `SecretStr`.

### Filesystem Paths (`core/configs/paths.py`)

`EnsurePaths()` is called at startup, creates required directories, and raises `FileNotFoundError` if `.env` is missing:
```
data/
  logs/bot/bot.log
  logs/api/api.log
  temp/
  recsys/embedding/model/   ← HuggingFace model cache
  recsys/opensearch/data/
  title/                    ← created by EnsurePaths(); used by title_store.py
```

`data/admins/admins.json` — optional seed file read by `EnsureDB()` to populate initial admin `is_admin` flags. Not managed at runtime.

`data/title/title.json` — runtime-managed, written by the admin Title sub-panel via `core/configs/title_store.SetTitle()`. Stores per-language hub titles; falls back to built-in defaults if unreadable.

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
                              #   migrate message PK from (message_id) to (chat_id, message_id)
                              #   if needed; seed admin is_admin flags from admins.json + defaults
   b. EnsureOpenSearchIndex() # Create OS index if missing
   c. EnsureSearchPipeline()  # Create normalization pipeline if missing
4. SetExceptionHandlers()     # Asyncio + Aiogram error handlers
5. SetAdminAlertHook(admin.NotifyOnLLMOutage)  # Wire the Claude out-of-credits admin
                              #   alert BEFORE the blocking startup sync (so an outage
                              #   during startup enrichment is caught too)
6. TestEmail()                # Verify SMTP credentials on startup, log warning if failed
7. SyncFromMyNES("startup")   # BLOCKING first sync — bot does not serve users until the
                              #   directory is mirrored (seconds if the index is intact;
                              #   full re-index if it was wiped). Proceeds on failure.
7. dp.start_polling(bot, drop_pending_updates=True)

OnStartup() [registered as dp.startup hook]:
1. SetMenu()                  # Register /start, /cancel bot commands
2. RegisterHandlerCancel(dp)  # /cancel handler
3. RegisterAdminHandlers(dp)  # Admin panel routers
4. RegisterClientHandlers(dp) # Hub, start, find, about, settings routers
5. RegisterHandlerZeroMessage(dp)  # Fallback handler
6. SetBotMiddleware(dp)       # Logging + block-check middleware
7. NotifyOnStartup()          # Send "Bot started" to all admins
8. ProcessPendingUpdates()    # Handle messages received while offline
9. StartSyncScheduler()       # Launch the PERIODIC MyNES sync loop (sleeps first, then
                              #   syncs every interval — the startup sync already ran in main())

OnShutdown() [registered as dp.shutdown hook]:
1. StopSyncScheduler()        # Cancel the sync loop (before clients close)
2. NotifyOnShutdown()         # Send bot.log to all admins
3. CloseOpenSearchClient()    # Graceful OpenSearch disconnect
4. CloseMyNesClient()         # Close the shared httpx client to MyNES
5. engine.dispose()           # Release SQLAlchemy connection pool
6. LoggerShutdown()           # Stop QueueListener (flushes pending records) + logging.shutdown()
```

Note: **No APScheduler for matching** — matching is still triggered manually by admins.
The MyNES directory sync, however, runs automatically on a lightweight asyncio
loop (`bot/lifecycle/sync_scheduler.py`), not APScheduler.

---

## MyNES Directory Sync (`api/sync.py`)

The bot mirrors the MyNES alumni directory into Postgres + OpenSearch instead of
fetching users one-by-one. `SyncFromMyNES(trigger)` runs once at startup
(**blocking, before polling** — see Startup Sequence), then every
`MYNES_SYNC_INTERVAL_SECONDS` (default 3600) via the periodic scheduler, plus on
demand from the admin MyNES panel. It is concurrency-guarded by an `asyncio.Lock`
(a second caller gets a `SyncReport(busy=True)` no-op).

```
SyncFromMyNES(trigger):
  1. FetchUsersList()  →  GET /user/list  (NO email/login in the payload!)
  2. Dedupe to one record per *alumni* nes_id (feed has byte-identical dupes).
     If the feed is empty → abort WITHOUT delisting (safety). A PARTIAL feed
     (>50% drop vs. currently-listed, past bootstrap size) also aborts.
  3. Content hash per profile over the raw feed JSON + the user's bio + a doc
     version tag. A profile is (re)worked only if the hash changed OR its doc is
     missing from the index (PresentDocIds self-heals a partial index loss).
  4. For each changed profile: build BuildProfileText (SearchText + bio) → enrich
     (EnrichTexts) → embed off the event loop → BulkUpsertProfilesOpenSearch, a
     FULL-replace write of the ONE unified doc (text + embedding + f_* fields).
     Bot-blocked alumni are excluded and any stale doc of theirs is dropped.
  5. Full-mirror upsert only the processed rows (SyncUpsertNesUsers) — overwrites
     removed fields with NULL; preserves nes_email + created_at. A profile that
     failed to index (or hit a transient enrichment error) gets hash=NULL so the
     next run retries it.
  6. DelistMissingNesUsers(fresh_ids): anyone no longer in the directory →
     listed=False, mynes_text_hash=NULL, and their OpenSearch doc is deleted
     (BulkDeleteOpenSearch) so they stop being searchable/matchable.
```

`SyncReport` carries per-run counters (fetched/alumni/upserted/changed/reindexed/
index_errors/**deferred**/delisted). **Out of Claude credits:** enrichment trips a
breaker and returns `skip` for the affected profiles; the sync leaves them entirely
untouched (no downgraded doc), counts them as `deferred`, and retries them next run
once credits return. `LAST_SYNC` is surfaced by the admin MyNES panel.

**Consequences worth knowing:**
- The directory is the source of truth for *discoverability*. A verified bot
  user who is **not** in `/user/list` is delisted: removed from Find search,
  excluded from matching (`CreateMatching` filters on `NesUser.listed`), AND
  paused from the bot until they re-share (`checks.IsUnshared`). (Aligns with
  MyNES's "Show in a class' directory" consent model; the old
  `data-sharing-permission` flag is gone.)
- Delisting deletes the *whole* OpenSearch doc. If such a user re-appears, the
  next sync rebuilds the unified doc; their self-written bio is folded back in
  automatically because it is part of the change hash and BuildProfileText.
- A bio edit re-indexes just that one profile interactively via
  `RebuildProfileForBio` (best-effort; the next sync self-heals it either way).
- Registration no longer calls MyNES at the confirm step — `ResolveNesUserByEmail`
  resolves nes_id at the email step (DB-first, byEmail fallback). Once MyNES adds
  email to `/user/list`, the byEmail fallback stops firing with zero code change.

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

Always use `bot/lib/message/io.py` — never call `bot.send_message()` / `edit_message_text()` directly:

```python
from nespresso.bot.lib.message.io import (
    SendMessage, SendDocument, EditMessage, EditPanel, PersonalMsg,
)

await SendMessage(chat_id=chat_id, text=text, reply_markup=kb)
await SendDocument(chat_id=chat_id, document=file, caption=text)

# Edit an existing panel in place (centralizes the "message is not modified" swallow)
await EditMessage(chat_id=chat_id, message_id=mid, text=text, reply_markup=kb)
await EditPanel(callback_query, text, reply_markup=kb)  # edits the callback's message

# Bulk send (rate-limited 30/sec)
await SendMessagesToGroup([PersonalMsg(chat_id=id, text=t) for id, t in pairs])
```

All four wrappers catch `TelegramForbiddenError` (bot blocked → `UserBlockedBot(chat_id)`, which unverifies the user and removes them from OpenSearch), plus `TelegramRetryAfter` (flood control — the send/edit is skipped, never an inline `sleep`) and other `TelegramAPIError`s, so one bad recipient can't crash a bulk loop. `EditMessage`/`EditPanel` additionally swallow the "message is not modified" no-op.

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
- **Alembic** scaffold exists (`alembic/` + `alembic.ini`; `env.py` targets `Base.metadata` and reuses the app's async `POSTGRES_DSN`), but it is additive — `versions/` has no migrations yet and **`EnsureDB()` remains the source of truth** (`metadata.create_all` + explicit `ALTER TABLE IF NOT EXISTS` for columns added to existing tables, plus an idempotent PK migration for the `message` table).
- The ML model (Alibaba GTE) is downloaded on first run to `data/recsys/embedding/model/` — ensure write permissions and network access.
- OpenSearch requires the `OPENSEARCH_INITIAL_ADMIN_PASSWORD` env var; TLS is disabled in dev config.
- Rate limiting for broadcasts uses `AsyncLimiter(30, 1)` — 30 messages per second — to stay within Telegram API limits.
- `HUB_MESSAGES` is an in-memory cache; `TgUser.panel_message_id` is the persistent DB-backed counterpart used to restore hub state after bot restarts.
- **Username caching:** `bot/lib/chat/username.GetTgUsername()` is hit on every inbound and outbound message via the logging hook; results are cached in a 5-minute TTL `cachetools.TTLCache` to avoid hammering Telegram and the DB.
- **Matching feedback analytics**: the Matching stats panel combines `GetMatchingStats()` (opted-out, total rounds, last round date/assignments) with `GetFeedbackStats()` (met / not_met / planning counts + response rate), so `MatchFeedback` rows are now surfaced.
- **Statistics panel** sends stats as new separate messages (not hub edits) to avoid Telegram's 4096-char message length limit.
- **DB export** (`⬇️ Download DB`) opens a sub-panel with one button per table; each writes a temporary single-sheet `.xlsx` to `data/temp/` via `openpyxl`, sends it, then deletes it (deletion is wrapped in `try/finally` so the temp file is removed even if `SendDocument` fails). The `message` table can be large — export time scales with row count.
- **User bio (about) indexing**: when a user saves their bio, `RebuildProfileForBio(nes_id, about)` rebuilds the ONE unified document (directory `SearchText` + bio → enrich → embed → full-replace write). A delisted user's bio is saved to Postgres but not indexed. Best-effort — the next sync self-heals it (the bio is part of the change hash).
- **OpenSearch deletes** (`DeleteUserOpenSearch`) swallow `NotFoundError`, since users may be unverified before their profile was ever indexed.
- **Help requests**: users can request help via Settings → Help → "Ask for help"; this silently notifies all admins with the user's `@username` and `chat_id`, subject to a 5-minute per-user cooldown (shared with the unverified `/help` path). Callbacks are also spam-guarded in the middleware.
- **Per-user search cap**: Find is capped at 60 searches/user/UTC-day (plus a 3s cooldown) since each query fires a paid ParseQuery + Rerank; over-quota users are turned away before any inference/LLM work.
- **Self-service privacy**: Settings → "My data & privacy" lets a user manage hidden profiles, export their own data (single-user xlsx), and delete their account (confirmed cascade delete via `DeleteAccountData` + OpenSearch doc drop).
- **LLM Find search**: parser, reranker, and enrichment all run on Claude Haiku 4.5 at **temperature 0** (deterministic — same query → same result) and are **fallback-safe** (a flaky/slow Claude API degrades to raw-query hybrid search, never an error). `CLAUDE_API_KEY` is required for these; without it the calls fail and fall back.
- **Search moderation never shows the raw query reason**: a rejected query (`is_valid_search=False`) is indistinguishable from "no results" so trolls get no signal; a deterministic slur regex backstops the LLM-down case.
- **Find-search eval kit** lives in `eval/`: `dataset.py` (predicate-based gold materialized from the live `/user/list`), `run_opensearch.py` (authoritative A/B against the real pipeline — run inside the bot container with `eval/` + `src/` bind-mounted), and `run_moderation.py` (rejection recall / false-positive rate for the moderation gate). The parser + reranker are non-deterministic at temperature > 0, so eval at temperature 0 is what makes A/B deltas trustworthy.

---

## Glossary

| Term | Meaning |
|------|---------|
| `chat_id` | Telegram user/chat identifier (BigInteger) |
| `nes_id` | NES alumni database ID |
| `verified` | User completed full registration flow |
| `is_admin` | DB column (TgUser) granting admin panel access |
| `matching_paused` | User opted out of matching rounds via Settings toggle |
| `listed` | Whether a NesUser is in the MyNES directory; gates discoverability, matching, AND bot access |
| unified doc | The one OpenSearch document per `nes_id` (`text` + `embedding` + `f_*`); replaced the old two-sided `mynes`/`cv` model |
| `ScrollingSearch` | Stateful paginated search session (excludes the searcher + their hidden profiles) |
| `UserContextService` | Unified service facade used by handlers |
| Admin store | DB-backed admin management (`TgUser.is_admin`) in `db/services/admin.py`; functions: `GetAdminIds`, `IsAdmin`, `AddAdmin`, `RemoveAdmin` |
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
| `EditMessage` / `EditPanel` | `io.py` wrappers for in-place panel edits (swallow "message is not modified", share `SendMessage`'s block/flood cleanup) |
| `DocAttr` | Namespace for the unified doc field names (`text`, `embedding`) in `index.py` |
| `ProfileReaction` | Per-user like/dislike + hide row on an alumni profile; reactions are analytics-only, hides exclude from Find + matching |
| `IsUnshared` | `checks.py` gate that pauses a verified user whose NesUser is unlisted, until they re-share |
| `DemoMatching` | Dry-run matching (same pool/exclusions as a real round) that persists nothing and notifies nobody — admin preview/export |
| `INDUSTRY_TAXONOMY` | Single source of truth rendering both `WORLD_KNOWLEDGE` (query side) and `DIRECTORY_KNOWLEDGE` (index/enrich side) |
| `SetAdminAlertHook` | Injects the bot's admin notifier into `recsys/searching/llm/alerts.py` (out-of-credits alert), keeping recsys free of `bot` imports |
| `SyncReport.deferred` | Count of profiles the sync left unprocessed because Claude ran out of credits (retried next run) |
| `PROGRAMS` | NES program vocabulary dict (`nes_user.py`); the parser derives its program-filter list from `list(PROGRAMS)` |
| `DEFAULT_ADMIN_IDS` | Hard-coded chat_ids in `core/configs/admin_ids.py` that are always admins; cannot be removed at runtime |
| `title_store` | JSON-backed per-language hub title overrides (`GetTitle`, `SetTitle`, `GetBothTitles`) used by the admin Title sub-panel |
| `AdminFilter` | Aiogram filter applied to every admin router so only `is_admin=True` users can trigger admin handlers |
| `ParseQuery` | Claude parser turning a query into `ParsedQuery(is_valid_search, semantic_query, expanded_terms, filters)` |
| `is_valid_search` | Parser moderation flag; `False` ⇒ search returns a plain "nothing found" |
| `expanded_terms` | Parser's query-side world-knowledge expansion (RU+EN), fed to a low-boost BM25 channel; gated by `QUERY_EXPANSION_ENABLED` |
| `WORLD_KNOWLEDGE` | Query-side employer→industry / role→skills taxonomy, generated from `INDUSTRY_TAXONOMY` (its index-side counterpart is `DIRECTORY_KNOWLEDGE`) |
| `Rerank` | Claude reranker that reorders the top-30 candidates against the raw query (temperature 0, fallback-safe) |
| `EnrichTexts` | Index-time **inline** world-knowledge annotation — additive parenthetical glosses woven in beside each entity, token-retention-guarded & fallback-safe (sync, `ENRICH_*` settings) |
| `PARSER_CACHE_HOURLY_THRESHOLD` | Rolling 60-min query count at/above which the parser prompt gets a 1-hour `cache_control` (default 5) |
