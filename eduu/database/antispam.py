# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from __future__ import annotations

from sqlite3 import OperationalError

from .core import database

conn = database.get_conn()
enabled_cache: dict[int, bool] = {}
column_ready = False


async def _ensure_column() -> None:
    global column_ready

    if column_ready:
        return

    cursor = await conn.execute("PRAGMA table_info(groups)")
    columns = {row[1] for row in await cursor.fetchall()}
    await cursor.close()
    if "antispam" not in columns:
        try:
            await conn.execute("ALTER TABLE groups ADD COLUMN antispam INTEGER DEFAULT 1")
            await conn.commit()
        except OperationalError as error:
            # Another concurrent handler may have added the column first.
            if "duplicate column name" not in str(error).lower():
                raise
    column_ready = True


async def is_antispam_enabled(chat_id: int) -> bool:
    if chat_id in enabled_cache:
        return enabled_cache[chat_id]

    await _ensure_column()
    cursor = await conn.execute("SELECT antispam FROM groups WHERE chat_id = ?", (chat_id,))
    row = await cursor.fetchone()
    await cursor.close()
    enabled = True if not row or row[0] is None else bool(row[0])
    enabled_cache[chat_id] = enabled
    return enabled


async def set_antispam(chat_id: int, enabled: bool) -> None:
    await _ensure_column()
    await conn.execute("UPDATE groups SET antispam = ? WHERE chat_id = ?", (enabled, chat_id))
    await conn.commit()
    enabled_cache[chat_id] = enabled
