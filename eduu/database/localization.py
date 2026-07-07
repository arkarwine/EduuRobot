# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from __future__ import annotations

from hydrogram.enums import ChatType

from eduu.utils.consts import GROUP_TYPES

from .core import database


async def set_db_lang(chat_id: int, chat_type: ChatType, lang_code: str) -> None:
    conn = database.get_conn()

    if chat_type in {ChatType.PRIVATE, ChatType.BOT}:
        await conn.execute(
            """
            INSERT INTO users(user_id, chat_lang)
            VALUES(?, ?)
            ON CONFLICT(user_id) DO UPDATE SET chat_lang = excluded.chat_lang
            """,
            (chat_id, lang_code),
        )
        await conn.commit()
    elif chat_type in GROUP_TYPES:  # groups and supergroups share the same table
        await conn.execute(
            """
            INSERT INTO groups(chat_id, chat_lang)
            VALUES(?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET chat_lang = excluded.chat_lang
            """,
            (chat_id, lang_code),
        )
        await conn.commit()
    elif chat_type == ChatType.CHANNEL:
        await conn.execute(
            """
            INSERT INTO channels(chat_id, chat_lang)
            VALUES(?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET chat_lang = excluded.chat_lang
            """,
            (chat_id, lang_code),
        )
        await conn.commit()
    else:
        raise TypeError(f"Unknown chat type '{chat_type}'.")


async def get_db_lang(chat_id: int, chat_type: ChatType) -> str | None:
    conn = database.get_conn()

    if chat_type == ChatType.PRIVATE:
        cursor = await conn.execute("SELECT chat_lang FROM users WHERE user_id = ?", (chat_id,))
        ul = await cursor.fetchone()
    elif chat_type in GROUP_TYPES:  # groups and supergroups share the same table
        cursor = await conn.execute("SELECT chat_lang FROM groups WHERE chat_id = ?", (chat_id,))
        ul = await cursor.fetchone()
    elif chat_type == ChatType.CHANNEL:
        cursor = await conn.execute("SELECT chat_lang FROM channels WHERE chat_id = ?", (chat_id,))
        ul = await cursor.fetchone()
    else:
        raise TypeError(f"Unknown chat type '{chat_type}'.")

    return ul[0] if ul else None
