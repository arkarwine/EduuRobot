# SPDX-License-Identifier: MIT

from __future__ import annotations

from .core import database

conn = database.get_conn()

DEFAULT_SETTINGS = {
    "batch_size": 5,
    "delay_seconds": 2,
    "hidden": True,
    "include_admins": True,
    "emoji": "🔔",
}
ALLOWED_SETTINGS = set(DEFAULT_SETTINGS)


async def _ensure_settings(chat_id: int) -> None:
    await conn.execute(
        "INSERT OR IGNORE INTO mention_all_settings(chat_id) VALUES (?)",
        (chat_id,),
    )
    await conn.commit()


async def get_mention_settings(chat_id: int) -> dict[str, bool | int | str]:
    await _ensure_settings(chat_id)
    cursor = await conn.execute(
        "SELECT batch_size, delay_seconds, hidden, include_admins, emoji "
        "FROM mention_all_settings WHERE chat_id = ?",
        (chat_id,),
    )
    row = await cursor.fetchone()
    await cursor.close()
    settings = dict(row) if row else DEFAULT_SETTINGS.copy()
    settings["hidden"] = bool(settings["hidden"])
    settings["include_admins"] = bool(settings["include_admins"])
    return settings


async def set_mention_setting(chat_id: int, key: str, value: bool | int | str) -> None:
    if key not in ALLOWED_SETTINGS:
        raise ValueError(f"Unknown mention-all setting: {key}")
    await _ensure_settings(chat_id)
    await conn.execute(
        f"UPDATE mention_all_settings SET {key} = ? WHERE chat_id = ?",
        (value, chat_id),
    )
    await conn.commit()
