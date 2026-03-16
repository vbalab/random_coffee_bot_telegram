import json
import os
from typing import Any

import openpyxl
from aiogram import types

from nespresso.bot.lib.message.io import SendDocument
from nespresso.core.configs.paths import DIR_TEMP


def ToJSONText(structure: dict[Any, Any] | list[dict[Any, Any]]) -> str:
    messages_json = json.dumps(structure, indent=3, ensure_ascii=False, default=str)
    messages_formatted = f"<pre>{messages_json}</pre>"

    return messages_formatted


async def SendTemporaryFileFromText(chat_id: int, text: str) -> None:
    file_path = DIR_TEMP / f"chat_id_{chat_id}.txt"

    with open(file_path, "w", encoding="utf-8") as file:
        file.write(text)

    await SendDocument(chat_id=chat_id, document=types.FSInputFile(file_path))

    os.remove(file_path)


async def SendTemporaryXlsxFile(
    chat_id: int,
    sheets: list[tuple[str, list[str], list[list[Any]]]],
    filename: str = "export",
) -> None:
    """Build a multi-sheet xlsx workbook and send it as a document, then delete it."""
    file_path = DIR_TEMP / f"{filename}_{chat_id}.xlsx"

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # type: ignore[arg-type]

    for sheet_name, headers, rows in sheets:
        ws = wb.create_sheet(title=sheet_name)
        ws.append(headers)
        for row in rows:
            ws.append(row)

    wb.save(file_path)

    await SendDocument(chat_id=chat_id, document=types.FSInputFile(file_path))

    os.remove(file_path)
