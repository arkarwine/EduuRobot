# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from __future__ import annotations

from .core import database

conn = database.get_conn()

DEFAULT_SETTINGS = {
    "enabled": True,
    "links": True,
    "forwards": True,
    "words": True,
    "flood": True,
    "repeats": True,
    "flood_limit": 10,
    "flood_window": 10,
    "repeat_limit": 4,
    "repeat_window": 20,
    "mute_minutes": 5,
}
BOOL_SETTINGS = {"enabled", "links", "forwards", "words", "flood", "repeats"}
INT_SETTINGS = {
    "flood_limit",
    "flood_window",
    "repeat_limit",
    "repeat_window",
    "mute_minutes",
}
ALLOWLIST_KINDS = {"user", "link", "source"}


async def _ensure_settings(chat_id: int) -> None:
    await conn.execute(
        "INSERT OR IGNORE INTO antispam_settings(chat_id) VALUES (?)",
        (chat_id,),
    )
    await conn.commit()


async def get_antispam_settings(chat_id: int) -> dict[str, bool | int]:
    await _ensure_settings(chat_id)
    cursor = await conn.execute(
        "SELECT enabled, links, forwards, words, flood, repeats, flood_limit, "
        "flood_window, repeat_limit, repeat_window, mute_minutes "
        "FROM antispam_settings WHERE chat_id = ?",
        (chat_id,),
    )
    row = await cursor.fetchone()
    await cursor.close()
    values = dict(row) if row else DEFAULT_SETTINGS.copy()
    for key in BOOL_SETTINGS:
        values[key] = bool(values[key])
    return values


async def set_antispam_setting(chat_id: int, key: str, value: bool | int) -> None:
    if key not in BOOL_SETTINGS | INT_SETTINGS:
        raise ValueError(f"Unknown anti-spam setting: {key}")
    await _ensure_settings(chat_id)
    await conn.execute(
        f"UPDATE antispam_settings SET {key} = ? WHERE chat_id = ?",
        (value, chat_id),
    )
    await conn.commit()


async def is_antispam_enabled(chat_id: int) -> bool:
    return bool((await get_antispam_settings(chat_id))["enabled"])


async def set_antispam(chat_id: int, enabled: bool) -> None:
    await set_antispam_setting(chat_id, "enabled", enabled)


async def add_antispam_allow(chat_id: int, kind: str, value: str) -> bool:
    if kind not in ALLOWLIST_KINDS:
        raise ValueError(f"Unknown allowlist kind: {kind}")
    cursor = await conn.execute(
        "INSERT OR IGNORE INTO antispam_allowlist(chat_id, kind, value) VALUES (?, ?, ?)",
        (chat_id, kind, value.casefold()),
    )
    await conn.commit()
    return cursor.rowcount > 0


async def remove_antispam_allow(chat_id: int, kind: str, value: str) -> bool:
    cursor = await conn.execute(
        "DELETE FROM antispam_allowlist WHERE chat_id = ? AND kind = ? AND value = ?",
        (chat_id, kind, value.casefold()),
    )
    await conn.commit()
    return cursor.rowcount > 0


async def get_antispam_allowlist(chat_id: int) -> dict[str, set[str]]:
    cursor = await conn.execute(
        "SELECT kind, value FROM antispam_allowlist WHERE chat_id = ? ORDER BY kind, value",
        (chat_id,),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    result = {kind: set() for kind in ALLOWLIST_KINDS}
    for row in rows:
        result[row["kind"]].add(row["value"])
    return result
