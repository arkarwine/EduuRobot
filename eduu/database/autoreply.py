# SPDX-License-Identifier: MIT

from __future__ import annotations

import json
from typing import Any

from eduu.database.core import database

DEFAULT_REACTIONS = ["👍", "❤️", "🔥", "👏", "😁"]
GLOBAL_AUTOREPLY_ID = 0
DEFAULT_SETTINGS = {
    "enabled": True,
    "mode": "random",
    "reply_chance": 50,
    "cooldown_seconds": 10,
    "rate_limit_per_minute": 0,
    "reactions_enabled": True,
    "reaction_chance": 25,
}

conn = database.get_conn()


def _global_chat_id(_chat_id: int | None = None) -> int:
    return GLOBAL_AUTOREPLY_ID


def _settings_from_row(row) -> dict[str, Any]:
    if not row:
        return DEFAULT_SETTINGS.copy()
    return {
        "enabled": bool(row["enabled"]),
        "mode": row["mode"],
        "reply_chance": int(row["reply_chance"]),
        "cooldown_seconds": int(row["cooldown_seconds"]),
        "rate_limit_per_minute": int(row["rate_limit_per_minute"]),
        "reactions_enabled": bool(row["reactions_enabled"]),
        "reaction_chance": int(row["reaction_chance"]),
    }


async def ensure_settings(chat_id: int | None = None) -> None:
    chat_id = _global_chat_id(chat_id)
    await conn.execute(
        "INSERT OR IGNORE INTO autoreply_settings(chat_id) VALUES(?)",
        (chat_id,),
    )
    await conn.commit()


async def get_settings(chat_id: int | None = None) -> dict[str, Any]:
    chat_id = _global_chat_id(chat_id)
    await ensure_settings(chat_id)
    cursor = await conn.execute(
        "SELECT * FROM autoreply_settings WHERE chat_id = ?",
        (chat_id,),
    )
    row = await cursor.fetchone()
    await cursor.close()
    return _settings_from_row(row)


async def set_setting(chat_id: int, key: str, value: Any) -> None:
    chat_id = _global_chat_id(chat_id)
    await ensure_settings(chat_id)
    await conn.execute(
        f"UPDATE autoreply_settings SET {key} = ? WHERE chat_id = ?",
        (value, chat_id),
    )
    await conn.commit()


async def add_response(
    chat_id: int,
    *,
    mode: str,
    keywords: list[str] | None,
    response_type: str,
    text: str | None = None,
    source_chat_id: int | None = None,
    source_message_id: int | None = None,
    label: str | None = None,
) -> None:
    chat_id = _global_chat_id(chat_id)
    await ensure_settings(chat_id)
    await conn.execute(
        """
        INSERT INTO autoreply_responses(
            chat_id, mode, keywords, response_type, text,
            source_chat_id, source_message_id, label
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            chat_id,
            mode,
            json.dumps(keywords or []),
            response_type,
            text,
            source_chat_id,
            source_message_id,
            label,
        ),
    )
    await conn.commit()


async def get_response(chat_id: int, response_id: int) -> dict[str, Any] | None:
    chat_id = _global_chat_id(chat_id)
    cursor = await conn.execute(
        "SELECT * FROM autoreply_responses WHERE chat_id = ? AND id = ?",
        (chat_id, response_id),
    )
    row = await cursor.fetchone()
    await cursor.close()
    if not row:
        return None
    return {
        "id": row["id"],
        "chat_id": row["chat_id"],
        "mode": row["mode"],
        "keywords": json.loads(row["keywords"] or "[]"),
        "response_type": row["response_type"],
        "text": row["text"],
        "source_chat_id": row["source_chat_id"],
        "source_message_id": row["source_message_id"],
        "label": row["label"],
    }


async def get_responses(chat_id: int, mode: str | None = None) -> list[dict[str, Any]]:
    chat_id = _global_chat_id(chat_id)
    query = "SELECT * FROM autoreply_responses WHERE chat_id = ?"
    params: list[Any] = [chat_id]
    if mode:
        query += " AND mode = ?"
        params.append(mode)
    query += " ORDER BY id"
    cursor = await conn.execute(query, params)
    rows = await cursor.fetchall()
    await cursor.close()
    return [
        {
            "id": row["id"],
            "chat_id": row["chat_id"],
            "mode": row["mode"],
            "keywords": json.loads(row["keywords"] or "[]"),
            "response_type": row["response_type"],
            "text": row["text"],
            "source_chat_id": row["source_chat_id"],
            "source_message_id": row["source_message_id"],
            "label": row["label"],
        }
        for row in rows
    ]


async def delete_response(chat_id: int, response_id: int) -> bool:
    chat_id = _global_chat_id(chat_id)
    cursor = await conn.execute(
        "DELETE FROM autoreply_responses WHERE chat_id = ? AND id = ?",
        (chat_id, response_id),
    )
    deleted = cursor.rowcount > 0
    await cursor.close()
    await conn.commit()
    return deleted


async def clear_responses(chat_id: int, mode: str | None = None) -> int:
    chat_id = _global_chat_id(chat_id)
    if mode:
        cursor = await conn.execute(
            "DELETE FROM autoreply_responses WHERE chat_id = ? AND mode = ?",
            (chat_id, mode),
        )
    else:
        cursor = await conn.execute(
            "DELETE FROM autoreply_responses WHERE chat_id = ?",
            (chat_id,),
        )
    deleted = cursor.rowcount
    await cursor.close()
    await conn.commit()
    return deleted


async def get_reactions(chat_id: int) -> list[str]:
    chat_id = _global_chat_id(chat_id)
    cursor = await conn.execute(
        "SELECT reaction FROM autoreply_reactions WHERE chat_id = ? ORDER BY reaction",
        (chat_id,),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [row["reaction"] for row in rows] or DEFAULT_REACTIONS.copy()


async def add_reaction(chat_id: int, reaction: str) -> bool:
    chat_id = _global_chat_id(chat_id)
    cursor = await conn.execute(
        "INSERT OR IGNORE INTO autoreply_reactions(chat_id, reaction) VALUES (?, ?)",
        (chat_id, reaction),
    )
    changed = cursor.rowcount > 0
    await cursor.close()
    await conn.commit()
    return changed


async def remove_reaction(chat_id: int, reaction: str) -> bool:
    chat_id = _global_chat_id(chat_id)
    cursor = await conn.execute(
        "DELETE FROM autoreply_reactions WHERE chat_id = ? AND reaction = ?",
        (chat_id, reaction),
    )
    changed = cursor.rowcount > 0
    await cursor.close()
    await conn.commit()
    return changed


async def add_keyword_reaction(chat_id: int, keywords: list[str], reaction: str) -> None:
    chat_id = _global_chat_id(chat_id)
    await conn.execute(
        """
        INSERT INTO autoreply_keyword_reactions(chat_id, keywords, reaction)
        VALUES (?, ?, ?)
        """,
        (chat_id, json.dumps(keywords), reaction),
    )
    await conn.commit()


async def get_keyword_reactions(chat_id: int) -> list[dict[str, Any]]:
    chat_id = _global_chat_id(chat_id)
    cursor = await conn.execute(
        "SELECT * FROM autoreply_keyword_reactions WHERE chat_id = ? ORDER BY id",
        (chat_id,),
    )
    rows = await cursor.fetchall()
    await cursor.close()
    return [
        {
            "id": row["id"],
            "keywords": json.loads(row["keywords"] or "[]"),
            "reaction": row["reaction"],
        }
        for row in rows
    ]


async def clear_keyword_reactions(chat_id: int) -> int:
    chat_id = _global_chat_id(chat_id)
    cursor = await conn.execute(
        "DELETE FROM autoreply_keyword_reactions WHERE chat_id = ?",
        (chat_id,),
    )
    deleted = cursor.rowcount
    await cursor.close()
    await conn.commit()
    return deleted


async def set_capture_state(
    user_id: int,
    *,
    chat_id: int | None = None,
    keywords: list[str] | None = None,
    reaction: bool = False,
    keyword_prompt: bool = False,
    reaction_prompt: bool = False,
) -> None:
    await conn.execute(
        """
        INSERT INTO autoreply_states(
            user_id, capture_chat_id, capture_keywords, capture_reaction,
            capture_keyword_prompt, capture_reaction_prompt
        )
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            capture_chat_id = excluded.capture_chat_id,
            capture_keywords = excluded.capture_keywords,
            capture_reaction = excluded.capture_reaction,
            capture_keyword_prompt = excluded.capture_keyword_prompt,
            capture_reaction_prompt = excluded.capture_reaction_prompt
        """,
        (
            user_id,
            chat_id,
            json.dumps(keywords or []),
            int(reaction),
            int(keyword_prompt),
            int(reaction_prompt),
        ),
    )
    await conn.commit()


async def get_capture_state(user_id: int) -> dict[str, Any]:
    cursor = await conn.execute(
        "SELECT * FROM autoreply_states WHERE user_id = ?",
        (user_id,),
    )
    row = await cursor.fetchone()
    await cursor.close()
    if not row:
        return {}
    return {
        "capture_chat_id": row["capture_chat_id"],
        "capture_keywords": json.loads(row["capture_keywords"] or "[]"),
        "capture_reaction": bool(row["capture_reaction"]),
        "capture_keyword_prompt": bool(row["capture_keyword_prompt"]),
        "capture_reaction_prompt": bool(row["capture_reaction_prompt"]),
    }


async def clear_capture_state(user_id: int) -> None:
    await conn.execute("DELETE FROM autoreply_states WHERE user_id = ?", (user_id,))
    await conn.commit()
