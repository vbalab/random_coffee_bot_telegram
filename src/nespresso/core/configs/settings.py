from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from nespresso.core.configs.paths import PATH_ENV


class Settings(BaseSettings):
    TELEGRAM_BOT_TOKEN: SecretStr

    EMAIL_ADDRESS: SecretStr
    EMAIL_PASSWORD: SecretStr

    POSTGRES_USER: SecretStr
    POSTGRES_PASSWORD: SecretStr
    POSTGRES_DB: SecretStr
    POSTGRES_HOST: SecretStr
    POSTGRES_PORT: SecretStr
    POSTGRES_DSN: SecretStr

    OPENSEARCH_INITIAL_ADMIN_PASSWORD: SecretStr

    # Anthropic / Claude — query understanding + reranking for Find search.
    CLAUDE_API_KEY: SecretStr
    QUERY_PARSER_MODEL: str = "claude-haiku-4-5"
    # The parser's large system prompt is prompt-cached, but a 1-hour cache write
    # costs 2x base input and only amortizes at >=3 queries/hour (break-even). We
    # therefore attach a 1h cache_control only once the rolling 60-minute query
    # count reaches this threshold (5 = break-even + safety margin); below it the
    # prompt is sent uncached so a lone write is never wasted.
    PARSER_CACHE_HOURLY_THRESHOLD: int = 5
    RERANK_MODEL: str = "claude-haiku-4-5"
    RERANK_ENABLED: bool = True
    RERANK_CANDIDATES: int = 30
    # Query-side world-knowledge expansion (`expanded_terms`) fed into the BM25
    # recall channel. Gated so it can be A/B'd independently; moderation +
    # semantic/filter parsing in the same parser call do NOT depend on this flag.
    QUERY_EXPANSION_ENABLED: bool = True
    # Index-time profile enrichment (world-knowledge expansion before embedding).
    ENRICH_ENABLED: bool = True
    ENRICH_MODEL: str = "claude-haiku-4-5"
    ENRICH_CONCURRENCY: int = 8
    # Enrichment runs in the background (indexing), so it gets a generous timeout
    # — unlike the interactive LLM_TIMEOUT_SECONDS used by parser/rerank — so calls
    # succeed instead of timing out and falling back to the un-enriched text.
    ENRICH_TIMEOUT_SECONDS: float = 60.0
    # Hard ceiling on each LLM call so a slow/broken API never stalls a search;
    # on timeout we fall back to the raw query / hybrid order.
    LLM_TIMEOUT_SECONDS: float = 8.0

    NES_API_BASE_URL: str = "https://my.nes.ru/new-api-2"

    # How often the bot mirrors the MyNES directory into Postgres + OpenSearch.
    # (The first sync runs at startup, blocking, before the bot serves users.)
    MYNES_SYNC_INTERVAL_SECONDS: int = 3600

    model_config = SettingsConfigDict(env_file=PATH_ENV, env_file_encoding="utf-8")


settings = Settings()
