import logging
from collections.abc import Sequence
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from nespresso.core.configs.settings import settings
from nespresso.db.models.nes_user import NesUser
from nespresso.db.models.schemas.nes_user import NesUserIn
from nespresso.db.services.user_context import GetUserContextService
from nespresso.recsys.searching.document import UpsertTextOpenSearch
from nespresso.recsys.searching.index import DocSide


def _NesUserPydanticToSQLAlchemy(instance: NesUserIn) -> NesUser:
    raw = instance.model_dump(mode="json", exclude_unset=True)
    return NesUser(**raw)


def _FormatScalarFields(user: NesUserIn) -> list[str]:
    labels = {
        "Name": user.name,
        "City": user.city,
        "Region": user.region,
        "Country": user.country,
        "Program": user.program,
        "Class": user.class_name,
    }

    return [f"{label} – {val}" for label, val in labels.items() if val]


def _FormatListFields(user: NesUserIn) -> list[str]:
    labels = {
        "Hobbies": user.hobbies,
        "Industry expertise": user.industry_expertise,
        "Country expertise": user.country_expertise,
        "Professional expertise": user.professional_expertise,
    }

    return [f"{label} – {', '.join(vals)}" for label, vals in labels.items() if vals]


def _FormatModelSection(
    label: str,
    models: BaseModel | Sequence[BaseModel] | None,
) -> str | None:
    if not models:
        return None

    if isinstance(models, BaseModel):
        items: Sequence[BaseModel] = [models]
    else:
        items = models

    entries: list[str] = []
    for m in items:
        data = m.model_dump()
        parts = [f"{k} – {v}" for k, v in data.items() if v is not None]

        if parts:
            entries.append(", ".join(parts))

    if not entries:
        return None

    sub = "\n".join(f"  – {e}" for e in entries)
    return f"{label}:\n{sub}"


def _GetNesUserModelText(nes_user: NesUserIn) -> str:
    sections: list[str] = []
    sections += _FormatScalarFields(nes_user)
    sections += _FormatListFields(nes_user)

    main_work = _FormatModelSection("Main work", nes_user.main_work)
    if main_work:
        sections.append(main_work)

    for label, attr in [
        ("Additional work", nes_user.additional_work),
        ("Pre-NES education", nes_user.pre_nes_education),
        ("Post-NES education", nes_user.post_nes_education),
    ]:
        section = _FormatModelSection(label, attr)
        if section:
            sections.append(section)

    return ".\n".join(sections)


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
    ctx = await GetUserContextService()
    await ctx.UpsertNesUser(alchemy_nes_user)

    logging.info(f"MyNES info for `nes_id={nes_id}` synced from API.", extra={"nes_id": nes_user.nes_id})

    text = _GetNesUserModelText(nes_user)
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
