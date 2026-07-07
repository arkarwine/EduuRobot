# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from __future__ import annotations

from .core import database

conn = database.get_conn()


async def _ensure_columns() -> None:
    for column in ("tiktok_enabled INTEGER",):
        try:
            await conn.execute(f"ALTER TABLE groups ADD COLUMN {column}")
            await conn.commit()
        except Exception:
            pass


async def get_tiktok(chat_id: int) -> bool:
    await _ensure_columns()
    cursor = await conn.execute("SELECT tiktok_enabled FROM groups WHERE chat_id = ?", (chat_id,))
    row = await cursor.fetchone()
    await cursor.close()
    if not row:
        return False
    enabled = row[0]
    if enabled is None:
        return False
    return bool(enabled)


async def toggle_tiktok(chat_id: int, mode: bool) -> None:
    await _ensure_columns()
    cursor = await conn.execute("SELECT chat_id FROM groups WHERE chat_id = ?", (chat_id,))
    row = await cursor.fetchone()
    await cursor.close()

    if row:
        await conn.execute("UPDATE groups SET tiktok_enabled = ? WHERE chat_id = ?", (mode, chat_id))
    else:
        await conn.execute("INSERT INTO groups (chat_id, tiktok_enabled) VALUES (?, ?)", (chat_id, mode))
    await conn.commit()
