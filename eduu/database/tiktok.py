# SPDX-License-Identifier: MIT

from __future__ import annotations

from .core import database

conn = database.get_conn()


async def _ensure_columns() -> None:
    try:
        await conn.execute("ALTER TABLE groups ADD COLUMN tiktok_autodl INTEGER DEFAULT 0")
        await conn.commit()
    except Exception:
        pass


async def get_tiktok_autodl(chat_id: int) -> bool:
    await _ensure_columns()
    cursor = await conn.execute(
        "SELECT tiktok_autodl FROM groups WHERE chat_id = ?",
        (chat_id,),
    )
    row = await cursor.fetchone()
    await cursor.close()
    return bool(row and row[0])


async def set_tiktok_autodl(chat_id: int, enabled: bool) -> None:
    await _ensure_columns()
    cursor = await conn.execute("SELECT chat_id FROM groups WHERE chat_id = ?", (chat_id,))
    row = await cursor.fetchone()
    await cursor.close()
    if row:
        await conn.execute(
            "UPDATE groups SET tiktok_autodl = ? WHERE chat_id = ?",
            (int(enabled), chat_id),
        )
    else:
        await conn.execute(
            "INSERT INTO groups (chat_id, tiktok_autodl) VALUES (?, ?)",
            (chat_id, int(enabled)),
        )
    await conn.commit()
