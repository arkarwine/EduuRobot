# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from .core import database

conn = database.get_conn()


async def get_rules(chat_id):
    cursor = await conn.execute("SELECT rules FROM groups WHERE chat_id = ?", (chat_id,))
    row = await cursor.fetchone()
    await cursor.close()
    return row[0] if row else None


async def set_rules(chat_id, rules):
    cursor = await conn.execute(
        "UPDATE groups SET rules = ? WHERE chat_id = ?",
        (rules, chat_id),
    )
    updated = cursor.rowcount
    await cursor.close()

    if updated == 0:
        await conn.execute(
            "INSERT INTO groups (chat_id, rules) VALUES (?, ?)",
            (chat_id, rules),
        )

    await conn.commit()
