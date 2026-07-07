# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from __future__ import annotations

import random
from typing import Any

from .core import database

DEFAULT_REPLY_CHANCE = 50
DEFAULT_COOLDOWN_SECONDS = 10
DEFAULT_RATE_LIMIT_PER_MINUTE = 0
DEFAULT_REACTION_CHANCE = 25

DEFAULT_SETTINGS: dict[str, Any] = {
    "enabled": True,
    "reply_chance": DEFAULT_REPLY_CHANCE,
    "cooldown_seconds": DEFAULT_COOLDOWN_SECONDS,
    "rate_limit_per_minute": DEFAULT_RATE_LIMIT_PER_MINUTE,
    "reactions_enabled": True,
    "reaction_chance": DEFAULT_REACTION_CHANCE,
}


async def _get_conn() -> Any:
    if not database.is_connected:
        await database.connect()
    return database.get_conn()


async def _ensure_settings() -> None:
    conn = await _get_conn()
    await conn.execute(
        "INSERT OR IGNORE INTO auto_reply_settings (id, enabled, reply_chance, cooldown_seconds, rate_limit_per_minute, reactions_enabled, reaction_chance) VALUES (1, ?, ?, ?, ?, ?, ?)",
        (
            1 if DEFAULT_SETTINGS["enabled"] else 0,
            DEFAULT_SETTINGS["reply_chance"],
            DEFAULT_SETTINGS["cooldown_seconds"],
            DEFAULT_SETTINGS["rate_limit_per_minute"],
            1 if DEFAULT_SETTINGS["reactions_enabled"] else 0,
            DEFAULT_SETTINGS["reaction_chance"],
        ),
    )
    await conn.commit()


def _response_from_row(row: Any) -> dict[str, Any]:
    return {
        "id": row[0],
        "chat_id": row[1],
        "text": row[2],
    }


async def get_settings(chat_id: int | None = None) -> dict[str, Any]:
    await _ensure_settings()
    conn = await _get_conn()
    if chat_id is None:
        cursor = await conn.execute(
            "SELECT enabled, reply_chance, cooldown_seconds, rate_limit_per_minute, reactions_enabled, reaction_chance FROM auto_reply_settings WHERE id = 1"
        )
        row = await cursor.fetchone()
        settings = {**DEFAULT_SETTINGS}
        if row:
            settings.update(
                {
                    "enabled": bool(row[0]),
                    "reply_chance": row[1],
                    "cooldown_seconds": row[2],
                    "rate_limit_per_minute": row[3],
                    "reactions_enabled": bool(row[4]),
                    "reaction_chance": row[5],
                }
            )
        return settings

    cursor = await conn.execute(
        "SELECT enabled, reply_chance, cooldown_seconds, rate_limit_per_minute, reactions_enabled, reaction_chance FROM auto_reply_chat_settings WHERE chat_id = ?",
        (chat_id,),
    )
    row = await cursor.fetchone()
    settings = await get_settings()
    if row:
        settings.update(
            {
                "enabled": bool(row[0]) if row[0] is not None else settings["enabled"],
                "reply_chance": row[1] if row[1] is not None else settings["reply_chance"],
                "cooldown_seconds": row[2] if row[2] is not None else settings["cooldown_seconds"],
                "rate_limit_per_minute": row[3] if row[3] is not None else settings["rate_limit_per_minute"],
                "reactions_enabled": bool(row[4]) if row[4] is not None else settings["reactions_enabled"],
                "reaction_chance": row[5] if row[5] is not None else settings["reaction_chance"],
            }
        )
    return settings


async def add_response(chat_id: int, text: str) -> int:
    conn = await _get_conn()
    cursor = await conn.execute(
        "INSERT INTO auto_reply_responses (chat_id, text) VALUES (?, ?)",
        (chat_id, text),
    )
    await conn.commit()
    return cursor.lastrowid


async def get_responses(chat_id: int) -> list[dict[str, Any]]:
    conn = await _get_conn()
    cursor = await conn.execute(
        "SELECT id, chat_id, text FROM auto_reply_responses WHERE chat_id = ?",
        (chat_id,),
    )
    rows = await cursor.fetchall()
    return [_response_from_row(row) for row in rows]


async def clear_responses(chat_id: int) -> int:
    conn = await _get_conn()
    cursor = await conn.execute(
        "DELETE FROM auto_reply_responses WHERE chat_id = ?",
        (chat_id,),
    )
    await conn.commit()
    return cursor.rowcount


async def next_response(chat_id: int) -> dict[str, Any] | None:
    responses = await get_responses(chat_id)
    return random.choice(responses) if responses else None


async def add_reaction(chat_id: int, reaction: str) -> str:
    conn = await _get_conn()
    cursor = await conn.execute(
        "INSERT OR IGNORE INTO auto_reply_reactions (chat_id, reaction) VALUES (?, ?)",
        (chat_id, reaction),
    )
    await conn.commit()
    return "added" if cursor.rowcount else "duplicate"


async def get_reactions(chat_id: int) -> list[str]:
    conn = await _get_conn()
    cursor = await conn.execute(
        "SELECT reaction FROM auto_reply_reactions WHERE chat_id = ?",
        (chat_id,),
    )
    return [row[0] for row in await cursor.fetchall()]


async def clear_reactions(chat_id: int) -> int:
    conn = await _get_conn()
    cursor = await conn.execute(
        "DELETE FROM auto_reply_reactions WHERE chat_id = ?",
        (chat_id,),
    )
    await conn.commit()
    return cursor.rowcount


async def set_enabled(chat_id: int, enabled: bool) -> None:
    conn = await _get_conn()
    await conn.execute(
        "INSERT INTO auto_reply_chat_settings (chat_id, enabled) VALUES (?, ?) ON CONFLICT(chat_id) DO UPDATE SET enabled = excluded.enabled",
        (chat_id, 1 if enabled else 0),
    )
    await conn.commit()


async def set_reply_chance(chat_id: int, chance: int) -> None:
    conn = await _get_conn()
    await conn.execute(
        "INSERT INTO auto_reply_chat_settings (chat_id, reply_chance) VALUES (?, ?) ON CONFLICT(chat_id) DO UPDATE SET reply_chance = excluded.reply_chance",
        (chat_id, chance),
    )
    await conn.commit()


async def set_cooldown(chat_id: int, seconds: int) -> None:
    conn = await _get_conn()
    await conn.execute(
        "INSERT INTO auto_reply_chat_settings (chat_id, cooldown_seconds) VALUES (?, ?) ON CONFLICT(chat_id) DO UPDATE SET cooldown_seconds = excluded.cooldown_seconds",
        (chat_id, seconds),
    )
    await conn.commit()


async def set_rate_limit(chat_id: int, per_minute: int) -> None:
    conn = await _get_conn()
    await conn.execute(
        "INSERT INTO auto_reply_chat_settings (chat_id, rate_limit_per_minute) VALUES (?, ?) ON CONFLICT(chat_id) DO UPDATE SET rate_limit_per_minute = excluded.rate_limit_per_minute",
        (chat_id, per_minute),
    )
    await conn.commit()


async def set_reactions_enabled(chat_id: int, enabled: bool) -> None:
    conn = await _get_conn()
    await conn.execute(
        "INSERT INTO auto_reply_chat_settings (chat_id, reactions_enabled) VALUES (?, ?) ON CONFLICT(chat_id) DO UPDATE SET reactions_enabled = excluded.reactions_enabled",
        (chat_id, 1 if enabled else 0),
    )
    await conn.commit()


async def set_reaction_chance(chat_id: int, chance: int) -> None:
    conn = await _get_conn()
    await conn.execute(
        "INSERT INTO auto_reply_chat_settings (chat_id, reaction_chance) VALUES (?, ?) ON CONFLICT(chat_id) DO UPDATE SET reaction_chance = excluded.reaction_chance",
        (chat_id, chance),
    )
    await conn.commit()
