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
    RERANK_MODEL: str = "claude-haiku-4-5"
    RERANK_ENABLED: bool = True
    RERANK_CANDIDATES: int = 30
    # Hard ceiling on each LLM call so a slow/broken API never stalls a search;
    # on timeout we fall back to the raw query / hybrid order.
    LLM_TIMEOUT_SECONDS: float = 8.0

    NES_API_BASE_URL: str = "https://my.nes.ru/new-api-2"

    # How often the bot mirrors the MyNES directory into Postgres + OpenSearch.
    # (The first sync runs at startup, blocking, before the bot serves users.)
    MYNES_SYNC_INTERVAL_SECONDS: int = 3600

    model_config = SettingsConfigDict(env_file=PATH_ENV, env_file_encoding="utf-8")


settings = Settings()
