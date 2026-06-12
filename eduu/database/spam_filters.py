# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from __future__ import annotations

import config

from .core import database

conn = database.get_conn()
filters_cache: dict[int, list[str]] = {}


def normalize_spam_word(word: str) -> str:
    return " ".join(word.casefold().split())


def _default_spam_words() -> set[str]:
    configured = getattr(config, "SPAM_FILTER_WORDS", ["bio"])
    return {normalize_spam_word(word) for word in configured if normalize_spam_word(word)}


async def _ensure_chat_defaults(chat_id: int) -> None:
    cursor = await conn.execute(
        "INSERT OR IGNORE INTO spam_filter_settings(chat_id) VALUES (?)",
        (chat_id,),
    )
    if cursor.rowcount:
        await conn.executemany(
            "INSERT OR IGNORE INTO spam_filters(chat_id, word) VALUES (?, ?)",
            [(chat_id, word) for word in _default_spam_words()],
        )
        await conn.commit()
    await cursor.close()


async def get_spam_filters(chat_id: int) -> list[str]:
    if chat_id in filters_cache:
        return filters_cache[chat_id]

    await _ensure_chat_defaults(chat_id)
    cursor = await conn.execute(
        "SELECT word FROM spam_filters WHERE chat_id = ? ORDER BY word",
        (chat_id,),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    words = [row[0] for row in rows]
    filters_cache[chat_id] = words
    return words


async def add_spam_filter(chat_id: int, word: str) -> bool:
    await _ensure_chat_defaults(chat_id)
    cursor = await conn.execute(
        "INSERT OR IGNORE INTO spam_filters(chat_id, word) VALUES (?, ?)",
        (chat_id, normalize_spam_word(word)),
    )
    await conn.commit()
    added = bool(cursor.rowcount)
    await cursor.close()
    filters_cache.pop(chat_id, None)
    return added


async def remove_spam_filter(chat_id: int, word: str) -> bool:
    await _ensure_chat_defaults(chat_id)
    cursor = await conn.execute(
        "DELETE FROM spam_filters WHERE chat_id = ? AND word = ?",
        (chat_id, normalize_spam_word(word)),
    )
    await conn.commit()
    removed = bool(cursor.rowcount)
    await cursor.close()
    filters_cache.pop(chat_id, None)
    return removed
