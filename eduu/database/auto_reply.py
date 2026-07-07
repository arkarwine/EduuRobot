# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from __future__ import annotations

import random
from typing import Any

from .core import database

conn = database.get_conn()

DEFAULT_REPLY_CHANCE = 50
DEFAULT_COOLDOWN_SECONDS = 10
DEFAULT_RATE_LIMIT_PER_MINUTE = 0
DEFAULT_REACTION_CHANCE = 25

DEFAULT_SETTINGS: dict[str, Any] = {
    "enabled": 1,
    "reply_chance": DEFAULT_REPLY_CHANCE,
    "cooldown_seconds": DEFAULT_COOLDOWN_SECONDS,
    "rate_limit_per_minute": DEFAULT_RATE_LIMIT_PER_MINUTE,
    "reactions_enabled": 1,
    "reaction_chance": DEFAULT_REACTION_CHANCE,
}


async def _ensure_settings() -> None:
    await conn.execute(
        "INSERT OR IGNORE INTO auto_reply_settings (id, enabled, reply_chance, cooldown_seconds, rate_limit_per_minute, reactions_enabled, reaction_chance) VALUES (1, ?, ?, ?, ?, ?, ?)",
        (
            DEFAULT_SETTINGS["enabled"],
            DEFAULT_SETTINGS["reply_chance"],
            DEFAULT_SETTINGS["cooldown_seconds"],
            DEFAULT_SETTINGS["rate_limit_per_minute"],
            DEFAULT_SETTINGS["reactions_enabled"],
            DEFAULT_SETTINGS["reaction_chance"],
        ),
    )
    await conn.commit()


def _response_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row[0],
        "chat_id": row[1],
        "source_chat_id": row[2],
        "source_message_id": row[3],
        "text": row[4],
        "label": row[5],
        "has_preview": bool(row[6]),
    }


async def get_settings() -> dict[str, Any]:
    await _ensure_settings()
    cursor = await conn.execute(
        "SELECT enabled, reply_chance, cooldown_seconds, rate_limit_per_minute, reactions_enabled, reaction_chance FROM auto_reply_settings WHERE id = 1"
    )
    row = await cursor.fetchone()
    settings = {**DEFAULT_SETTINGS}
    if row:
        settings.update(
            {
                "enabled": row[0],
                "reply_chance": row[1],
                "cooldown_seconds": row[2],
                "rate_limit_per_minute": row[3],
                "reactions_enabled": row[4],
                "reaction_chance": row[5],
            }
        )
    return settings


async def add_response(
    chat_id: int,
    source_chat_id: int | None = None,
    source_message_id: int | None = None,
    text: str | None = None,
    label: str | None = None,
    has_preview: bool = False,
) -> int:
    cursor = await conn.execute(
        "INSERT INTO auto_reply_responses (chat_id, source_chat_id, source_message_id, text, label, has_preview) VALUES (?, ?, ?, ?, ?, ?)",
        (
            chat_id,
            source_chat_id,
            source_message_id,
            text,
            label,
            1 if has_preview else 0,
        ),
    )
    await conn.commit()
    return cursor.lastrowid


async def get_responses(chat_id: int) -> list[dict[str, Any]]:
    cursor = await conn.execute(
        "SELECT id, chat_id, source_chat_id, source_message_id, text, label, has_preview FROM auto_reply_responses WHERE chat_id = ?",
        (chat_id,),
    )
    rows = await cursor.fetchall()
    return [_response_from_row(row) for row in rows]


async def clear_responses(chat_id: int) -> int:
    cursor = await conn.execute(
        "DELETE FROM auto_reply_responses WHERE chat_id = ?",
        (chat_id,),
    )
    await conn.commit()
    return cursor.rowcount


async def remove_response(chat_id: int, response_id: int) -> int:
    cursor = await conn.execute(
        "DELETE FROM auto_reply_responses WHERE chat_id = ? AND id = ?",
        (chat_id, response_id),
    )
    await conn.commit()
    return cursor.rowcount


async def next_response(chat_id: int) -> dict[str, Any] | None:
    responses = await get_responses(chat_id)
    return random.choice(responses) if responses else None


async def add_reaction(chat_id: int, reaction: str) -> str:
    cursor = await conn.execute(
        "INSERT OR IGNORE INTO auto_reply_reactions (chat_id, reaction) VALUES (?, ?)",
        (chat_id, reaction),
    )
    await conn.commit()
    return "added" if cursor.rowcount else "duplicate"


async def get_reactions(chat_id: int) -> list[str]:
    cursor = await conn.execute(
        "SELECT reaction FROM auto_reply_reactions WHERE chat_id = ?",
        (chat_id,),
    )
    return [row[0] for row in await cursor.fetchall()]


async def clear_reactions(chat_id: int) -> int:
    cursor = await conn.execute(
        "DELETE FROM auto_reply_reactions WHERE chat_id = ?",
        (chat_id,),
    )
    await conn.commit()
    return cursor.rowcount


async def set_enabled(enabled: bool) -> None:
    await _ensure_settings()
    await conn.execute(
        "UPDATE auto_reply_settings SET enabled = ? WHERE id = 1",
        (1 if enabled else 0,),
    )
    await conn.commit()


async def set_reply_chance(chance: int) -> None:
    await _ensure_settings()
    await conn.execute(
        "UPDATE auto_reply_settings SET reply_chance = ? WHERE id = 1",
        (chance,),
    )
    await conn.commit()


async def set_cooldown(seconds: int) -> None:
    await _ensure_settings()
    await conn.execute(
        "UPDATE auto_reply_settings SET cooldown_seconds = ? WHERE id = 1",
        (seconds,),
    )
    await conn.commit()


async def set_rate_limit(per_minute: int) -> None:
    await _ensure_settings()
    await conn.execute(
        "UPDATE auto_reply_settings SET rate_limit_per_minute = ? WHERE id = 1",
        (per_minute,),
    )
    await conn.commit()


async def set_reactions_enabled(enabled: bool) -> None:
    await _ensure_settings()
    await conn.execute(
        "UPDATE auto_reply_settings SET reactions_enabled = ? WHERE id = 1",
        (1 if enabled else 0,),
    )
    await conn.commit()


async def set_reaction_chance(chance: int) -> None:
    await _ensure_settings()
    await conn.execute(
        "UPDATE auto_reply_settings SET reaction_chance = ? WHERE id = 1",
        (chance,),
    )
    await conn.commit()
