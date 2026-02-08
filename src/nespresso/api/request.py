import logging
from typing import Any

import httpx
from pydantic import ValidationError

from nespresso.core.configs.settings import settings
from nespresso.db.models.nes_user import NesUser
from nespresso.db.models.schemas.nes_user import NesUserIn
from nespresso.db.services.user_context import GetUserContextService
from nespresso.recsys.searching.document import UpsertTextOpenSearch
from nespresso.recsys.searching.index import DocSide


def _NesUserPydanticToSQLAlchemy(instance: NesUserIn) -> NesUser:
    raw = instance.model_dump(mode="json", exclude_unset=True)
    return NesUser(**raw)


async def _FetchNesUserData(nes_id: int) -> dict[str, Any]:
    base_url = settings.NES_API_BASE_URL.rstrip("/")
    url = f"{base_url}/user/{nes_id}"

    async with httpx.AsyncClient() as client:
        response = await client.get(url, headers={"accept": "application/json"})
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError:
        logging.exception(
            "Failed to fetch NES user data.",
            extra={"nes_id": nes_id, "status_code": response.status_code},
        )
        # raise TODO

    return response.json()


async def GetNesUserFromMyNES(nes_id: int) -> NesUserIn:
    data = await _FetchNesUserData(nes_id)

    try:
        nes_user = NesUserIn.model_validate(data)
    except ValidationError:
        logging.exception(
            "Failed to parse NES user data.",
            extra={"nes_id": nes_id, "payload": data},
        )
        return
        # raise TODO

    alchemy_nes_user = _NesUserPydanticToSQLAlchemy(nes_user)

    logging.info(
        f"MyNES info for `nes_id={nes_id}` synced from API.",
        extra={"nes_id": nes_user.nes_id},
    )

    ctx = await GetUserContextService()
    await ctx.UpsertNesUser(alchemy_nes_user)

    text = alchemy_nes_user.FullDescription()
    await UpsertTextOpenSearch(
        nes_id=nes_user.nes_id,
        side=DocSide.mynes,
        text=text,
    )

    return nes_user


async def _SetDataSharingPermission(nes_id: int, permission: bool) -> None:
    base_url = settings.NES_API_BASE_URL.rstrip("/")
    url = f"{base_url}/data-sharing-permission"
    payload = {"nes_id": nes_id, "permission": permission}

    async with httpx.AsyncClient() as client:
        response = await client.post(
            url,
            json=payload,
            headers={"accept": "application/json"},
        )

    try:
        response.raise_for_status()
    except httpx.HTTPStatusError:
        logging.exception(
            "Failed to update data sharing permission.",
            extra={
                "nes_id": nes_id,
                "permission": permission,
                "status_code": response.status_code,
            },
        )
        # raise TODO

    logging.info(
        f"MyNES data sharing permission for `nes_id={nes_id}` updated to `{permission}`.",
        extra={"nes_id": nes_id, "permission": permission},
    )


async def AllowDataSharingPermission(nes_id: int) -> None:
    await _SetDataSharingPermission(nes_id, True)


async def DenyDataSharingPermission(nes_id: int) -> None:
    await _SetDataSharingPermission(nes_id, False)
