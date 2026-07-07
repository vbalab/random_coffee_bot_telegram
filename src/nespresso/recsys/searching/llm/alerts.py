"""
Turn a specific, actionable Claude API outage into a loud admin alert.

Every LLM caller (parser, reranker, enrichment) is fallback-safe: it swallows API
errors and degrades gracefully so a flaky Claude API never breaks Find search.
That resilience also HIDES a total outage — when the org runs OUT OF CREDITS,
every call 400s and the only symptom is silently worse search + enrichment, with
no signal to the operators. This module classifies that case and raises a loud,
throttled notification so admins know immediately what's wrong (and how to fix it).

Layering: `recsys` must not import `bot`. The bot injects an async notifier via
`SetAdminAlertHook` at startup; when no hook is set (a standalone sync/eval run)
we only log. Detection + throttling live here; delivery is the bot's concern.
"""

import logging
import time
from collections.abc import Awaitable, Callable

# Throttle: at most one admin ping per this window. A credit-less reindex makes
# thousands of failing calls — without this every one would notify.
_ALERT_INTERVAL_SECONDS = 1800.0


class LLMCreditsExhaustedError(RuntimeError):
    """
    The Claude API rejected a request because the organization is out of usage
    credits. Named + greppable so logs and the admin message identify the problem
    unambiguously. Not raised into the fallback-safe callers (that would defeat
    their graceful degradation) — used for classification, logging, and alerting.
    """


_AlertHook = Callable[[str], Awaitable[None]]
_hook: _AlertHook | None = None
_last_alert_monotonic: float | None = None


def SetAdminAlertHook(hook: _AlertHook | None) -> None:
    """Wire (or clear) the admin notifier. Called by the bot at startup."""
    global _hook
    _hook = hook


def IsCreditsExhausted(exc: BaseException) -> bool:
    """
    True if `exc` is Anthropic's 'out of usage credits' / low-balance rejection
    (a 400 with a distinctive message). Matched on the message text so it is
    robust across SDK exception classes.
    """
    text = str(getattr(exc, "message", "") or exc).lower()
    return (
        "credit balance is too low" in text
        or "out of usage credits" in text
        or ("credit" in text and ("balance" in text or "usage" in text))
    )


_ALERT_MESSAGE = (
    "⚠️ Claude API unavailable — the organization is OUT OF CREDITS.\n\n"
    "Find search (query parsing + reranking) and profile enrichment are running "
    "in degraded fallback mode until this is fixed.\n\n"
    "Add credits here: https://console.anthropic.com/settings/billing"
)


async def ReportLLMError(exc: BaseException, context: str) -> None:
    """
    Classify a swallowed LLM error. On the actionable 'out of credits' case, log
    it as `LLMCreditsExhaustedError` and — throttled — notify admins. Only that
    case alerts; ordinary timeouts/5xx stay quiet (the caller already logs them).
    Never raises: it runs inside the callers' fallback path.
    """
    if not IsCreditsExhausted(exc):
        return

    global _last_alert_monotonic
    now = time.monotonic()
    if (
        _last_alert_monotonic is not None
        and now - _last_alert_monotonic < _ALERT_INTERVAL_SECONDS
    ):
        return  # already alerted recently

    _last_alert_monotonic = now
    logging.critical(
        "%s: Claude API out of credits (context=%s). Find search + enrichment "
        "are degraded until credits are added.",
        LLMCreditsExhaustedError.__name__,
        context,
    )
    if _hook is None:
        return
    try:
        await _hook(_ALERT_MESSAGE)
    except Exception:
        logging.warning("Failed to deliver LLM-outage admin alert.", exc_info=True)
