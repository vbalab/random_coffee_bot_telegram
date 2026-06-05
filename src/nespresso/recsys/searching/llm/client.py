"""
Shared async Anthropic client for query understanding + reranking.

Kept dependency-light (no OpenSearch / torch imports) so the LLM modules can be
imported and exercised in isolation. Every caller is responsible for its own
fallback when a request fails — a flaky Claude API must never break Find search.
"""

import logging

from anthropic import AsyncAnthropic

from nespresso.core.configs.settings import settings

# max_retries=1: one quick retry on transient 429/5xx, then fall back. The per-
# request timeout is set by each caller via with_options(), bounded by
# LLM_TIMEOUT_SECONDS, so a hung request can't stall a search indefinitely.
client = AsyncAnthropic(
    api_key=settings.CLAUDE_API_KEY.get_secret_value(),
    max_retries=1,
)


async def CloseLLMClient() -> None:
    try:
        await client.close()
    except Exception:
        logging.debug("Failed to close Anthropic client", exc_info=True)
