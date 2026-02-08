import logging
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Body, status
from pydantic import BaseModel

from nespresso.db.models.nes_user import NesUser
from nespresso.db.models.schemas.nes_user import NesUserIn


def NesUserPydanticToSQLAlchemy(instance: NesUserIn) -> NesUser:
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


def GetNesUserModelText(nes_user: NesUserIn) -> str:
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
