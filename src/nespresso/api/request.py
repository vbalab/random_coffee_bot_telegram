import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any, TypeVar

import httpx
from pydantic import ValidationError

from nespresso.core.configs.settings import settings
from nespresso.db.models.nes_user import NesUser
from nespresso.db.models.schemas.nes_user import NesUserIn
from nespresso.db.services.user_context import GetUserContextService
from nespresso.recsys.searching.document import UpsertTextOpenSearch
from nespresso.recsys.searching.filtering import StructuredFields
from nespresso.recsys.searching.index import DocSide

_HTTP_TIMEOUT = httpx.Timeout(connect=10.0, read=20.0, write=20.0, pool=10.0)
# The directory feed (`/user/list`) is a single multi-MB response; give it room.
_LIST_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=20.0, pool=10.0)
_HTTP_LIMITS = httpx.Limits(max_connections=10, max_keepalive_connections=5)
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 0.5

_http_client = httpx.AsyncClient(timeout=_HTTP_TIMEOUT, limits=_HTTP_LIMITS)


async def CloseMyNesClient() -> None:
    await _http_client.aclose()


T = TypeVar("T")


async def _SendWithRetry(send: Callable[[], Awaitable[T]], context: str) -> T:
    last_exc: Exception | None = None
    for attempt in range(1, _RETRY_ATTEMPTS + 1):
        try:
            return await send()
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            last_exc = e
            if attempt == _RETRY_ATTEMPTS:
                break
            delay = _RETRY_BACKOFF_SECONDS * (2 ** (attempt - 1))
            logging.warning(
                f"{context}: transient error ({type(e).__name__}); "
                f"retry {attempt}/{_RETRY_ATTEMPTS - 1} in {delay:.1f}s"
            )
            await asyncio.sleep(delay)
    assert last_exc is not None
    raise last_exc


def _NesUserPydanticToSQLAlchemy(instance: NesUserIn) -> NesUser:
    raw = instance.model_dump(mode="json", exclude_unset=True)
    model = NesUser(**raw)
    # Derive scalar program/class_name from `programs` (same as the sync path) so a
    # byEmail-resolved user also gets a primary program for display/analytics.
    model.program, model.class_name = instance.primary_program()
    return model


# --------------------------------------------------------------------------- #
# Bulk directory feed: GET /user/list                                         #
# --------------------------------------------------------------------------- #
# Returns every user with "Show in a class' directory" enabled. The payload    #
# carries NO email/login, so it is the single source of *profile* data but     #
# cannot resolve an email -> nes_id by itself (see ResolveNesUserByEmail).     #


async def FetchUsersList() -> list[NesUserIn]:
    """
    Fetch and parse the full MyNES directory (`GET /user/list`).

    Returns one `NesUserIn` per valid record; records that fail validation are
    skipped (and logged) rather than aborting the whole sync. Duplicate nes_ids
    (the feed contains byte-identical duplicates) are left for the caller to
    dedupe.
    """
    base_url = settings.NES_API_BASE_URL.rstrip("/")
    url = f"{base_url}/user/list"

    response = await _SendWithRetry(
        lambda: _http_client.get(
            url, headers={"accept": "application/json"}, timeout=_LIST_TIMEOUT
        ),
        context="MyNES fetch /user/list",
    )
    response.raise_for_status()

    payload = response.json()
    if not isinstance(payload, list):
        raise ValueError(
            f"MyNES /user/list returned {type(payload).__name__}, expected list"
        )

    users: list[NesUserIn] = []
    invalid = 0
    for record in payload:
        try:
            users.append(NesUserIn.model_validate(record))
        except ValidationError:
            invalid += 1
            logging.warning(
                "Skipping invalid MyNES directory record.",
                extra={"record": record},
            )

    logging.info(
        f"MyNES /user/list fetched: {len(users)} parsed, {invalid} skipped.",
        extra={"parsed": len(users), "invalid": invalid},
    )
    return users


# --------------------------------------------------------------------------- #
# Single-user lookup: GET /user/byEmail/{email}                                #
# --------------------------------------------------------------------------- #
# Used only as a fallback during registration, to resolve an email -> nes_id   #
# when the synced directory has no email for it yet.                           #


async def _FetchNesUserData(nes_email: str) -> dict[str, Any]:
    base_url = settings.NES_API_BASE_URL.rstrip("/")
    url = f"{base_url}/user/byEmail/{nes_email}"

    response = await _SendWithRetry(
        lambda: _http_client.get(url, headers={"accept": "application/json"}),
        context=f"MyNES fetch nes_email={nes_email}",
    )
    # Raise on any non-2xx; ResolveNesUserByEmail classifies the status (403/404
    # are expected "not available" cases, not errors) and logs accordingly.
    response.raise_for_status()

    return response.json()


async def GetNesUserFromMyNES(nes_email: str) -> NesUserIn | None:
    """
    Fetch a single user by email, persist their profile (DB + OpenSearch) and
    return the parsed model. The `mynes_text_hash` is intentionally left unset
    so the next directory sync (re)embeds them once — this keeps the OpenSearch
    document authoritative without this path having to guarantee indexing.
    """
    data = await _FetchNesUserData(nes_email)

    try:
        nes_user = NesUserIn.model_validate(data)
    except ValidationError:
        logging.exception(
            "Failed to parse NES user data.",
            extra={"nes_email": nes_email, "payload": data},
        )
        return None

    logging.info(
        f"MyNES info for `nes_email={nes_email}` synced from API.",
        extra={"nes_email": nes_email, "nes_id": nes_user.nes_id},
    )

    if nes_user.alumni:
        alchemy_nes_user = _NesUserPydanticToSQLAlchemy(nes_user)
        alchemy_nes_user.nes_email = nes_email
        ctx = await GetUserContextService()
        await ctx.UpsertNesUser(alchemy_nes_user)

        await UpsertTextOpenSearch(
            nes_id=nes_user.nes_id,
            side=DocSide.mynes,
            text=alchemy_nes_user.SearchText(),
            extra=StructuredFields(alchemy_nes_user),
        )

    return nes_user


class EmailLookup(str, Enum):
    """Outcome of resolving a registration email against MyNES."""

    found = "found"  # resolvable alumnus (nes_id set)
    not_found = "not_found"  # 404 — no such NES email
    not_shared = "not_shared"  # 403 — exists but not shared in the directory


@dataclass
class EmailResolution:
    status: EmailLookup
    nes_id: int | None = None
    alumni: bool = False


async def ResolveNesUserByEmail(nes_email: str) -> EmailResolution:
    """
    Resolve an email for registration.

    DB-first: if the synced `nes_user` table already knows this email, use it
    with zero API calls (the path the whole migration is built toward — and the
    only path once MyNES adds email to `/user/list`). Otherwise fall back to a
    single `GET /user/byEmail/{email}`, which also binds the email to the row so
    subsequent registrations resolve from the DB.

    Status mapping for the byEmail fallback:
      - 200 + alumnus -> ``found`` (nes_id, alumni)
      - 404           -> ``not_found``   (no such NES email)
      - 403           -> ``not_shared``  ("Show in a class' directory" is off)
    Transient / 5xx errors propagate so the caller can show a "try again later"
    message rather than a definitive verdict.
    """
    ctx = await GetUserContextService()

    row = await ctx.GetNesUserByEmail(nes_email)
    if row is not None:
        return EmailResolution(EmailLookup.found, row.nes_id, bool(row.alumni))

    try:
        nes_user = await GetNesUserFromMyNES(nes_email)
    except httpx.HTTPStatusError as e:
        status = e.response.status_code
        if status == 404:
            logging.info(f"MyNES byEmail nes_email={nes_email}: 404 (not found).")
            return EmailResolution(EmailLookup.not_found)
        if status == 403:
            logging.info(
                f"MyNES byEmail nes_email={nes_email}: 403 (not shared in directory)."
            )
            return EmailResolution(EmailLookup.not_shared)
        logging.exception(
            "MyNES byEmail unexpected HTTP error.",
            extra={"nes_email": nes_email, "status_code": status},
        )
        raise

    if nes_user is None:
        # 200 but payload unparseable — treat as not found rather than crash.
        return EmailResolution(EmailLookup.not_found)
    return EmailResolution(EmailLookup.found, nes_user.nes_id, bool(nes_user.alumni))
