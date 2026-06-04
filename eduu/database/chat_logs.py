# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from hydrogram import Client
from hydrogram.types import Chat

from config import LOG_CHAT
from eduu.database import database

conn = database.get_conn()


async def log_chat(chat: Chat, client: Client | None = None) -> bool:
    """Log a chat that the bot has joined.

    Returns True if the chat was newly inserted, False if it already existed.
    """
    chat_title = chat.title or chat.first_name or chat.username or str(chat.id)

    try:
        cursor = await conn.execute(
            "SELECT chat_id FROM chat_logs WHERE chat_id = ?",
            (chat.id,),
        )
        existing = await cursor.fetchone()

        if existing:
            await conn.execute(
                """
                UPDATE chat_logs
                SET last_seen = CURRENT_TIMESTAMP,
                    chat_title = ?
                WHERE chat_id = ?
                """,
                (chat_title, chat.id),
            )
            await conn.commit()
            return False

        await conn.execute(
            """
            INSERT INTO chat_logs (chat_id, chat_type, chat_title)
            VALUES (?, ?, ?)
            """,
            (chat.id, str(chat.type), chat_title),
        )
        await conn.commit()

        if client is not None and chat.id != LOG_CHAT:
            username = f"@{chat.username}" if chat.username else "N/A"
            text = (
                "<b>New chat/user logged:</b>\n\n"
                f"<b>ID:</b> <code>{chat.id}</code>\n"
                f"<b>Type:</b> {chat.type}\n"
                f"<b>Title:</b> {chat_title}\n"
                f"<b>Username:</b> {username}"
            )
            try:
                await client.send_message(LOG_CHAT, text)
            except Exception:
                pass

        return True
    except Exception as e:
        print(f"Error logging chat {chat.id}: {e}")
        return False


async def get_all_chats():
    """Get all logged chats"""
    cursor = await conn.execute("SELECT chat_id, chat_type FROM chat_logs")
    rows = await cursor.fetchall()
    return rows


async def get_all_chat_ids():
    """Get all logged chat IDs"""
    cursor = await conn.execute("SELECT chat_id FROM chat_logs")
    rows = await cursor.fetchall()
    return [row[0] for row in rows]


async def get_chat_stats():
    """Get statistics about logged chats"""
    cursor = await conn.execute(
        "SELECT chat_type, COUNT(*) as count FROM chat_logs GROUP BY chat_type"
    )
    rows = await cursor.fetchall()
    return rows
