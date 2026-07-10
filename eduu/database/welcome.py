# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from __future__ import annotations

from typing import Optional, Tuple

from .core import database

conn = database.get_conn()
DEFAULT_GREETING_DELETE_SECONDS = 10
GREETING_DELETE_DEFAULT_KIND = "greeting_delete_seconds"


async def _ensure_columns():
    """Attempt to add welcome/goodbye columns if they don't exist."""
    await conn.execute(
        """
        CREATE TABLE IF NOT EXISTS welcome_defaults(
            kind TEXT PRIMARY KEY,
            text TEXT
        )
        """
    )
    columns = {
        "welcome_media_file_id": "TEXT",
        "welcome_media_type": "TEXT",
        "goodbye": "TEXT",
        "goodbye_enabled": "INTEGER",
        "goodbye_media_file_id": "TEXT",
        "goodbye_media_type": "TEXT",
        "greeting_delete_seconds": "INTEGER DEFAULT 10",
    }
    for column, column_type in columns.items():
        try:
            await conn.execute(f"ALTER TABLE groups ADD COLUMN {column} {column_type}")
            await conn.commit()
        except Exception:
            pass


async def get_default_template(kind: str, fallback: str) -> str:
    await _ensure_columns()
    cursor = await conn.execute(
        "SELECT text FROM welcome_defaults WHERE kind = ?",
        (kind,),
    )
    row = await cursor.fetchone()
    return row[0] if row and row[0] else fallback


async def set_default_template(kind: str, text: str) -> None:
    await _ensure_columns()
    await conn.execute(
        """
        INSERT INTO welcome_defaults(kind, text)
        VALUES(?, ?)
        ON CONFLICT(kind) DO UPDATE SET text = excluded.text
        """,
        (kind, text),
    )
    await conn.commit()


async def reset_default_template(kind: str) -> None:
    await _ensure_columns()
    await conn.execute("DELETE FROM welcome_defaults WHERE kind = ?", (kind,))
    await conn.commit()


async def get_default_greeting_delete_seconds() -> int:
    await _ensure_columns()
    cursor = await conn.execute(
        "SELECT text FROM welcome_defaults WHERE kind = ?",
        (GREETING_DELETE_DEFAULT_KIND,),
    )
    row = await cursor.fetchone()
    if not row or row[0] is None:
        return DEFAULT_GREETING_DELETE_SECONDS
    try:
        return max(0, int(row[0]))
    except (TypeError, ValueError):
        return DEFAULT_GREETING_DELETE_SECONDS


async def set_default_greeting_delete_seconds(seconds: int) -> None:
    await _ensure_columns()
    seconds = max(0, min(seconds, 86400))
    await conn.execute(
        """
        INSERT INTO welcome_defaults(kind, text)
        VALUES(?, ?)
        ON CONFLICT(kind) DO UPDATE SET text = excluded.text
        """,
        (GREETING_DELETE_DEFAULT_KIND, str(seconds)),
    )
    await conn.commit()


async def reset_default_greeting_delete_seconds() -> None:
    await _ensure_columns()
    await conn.execute(
        "DELETE FROM welcome_defaults WHERE kind = ?",
        (GREETING_DELETE_DEFAULT_KIND,),
    )
    await conn.commit()


async def get_welcome(chat_id: int) -> Tuple[Optional[str], bool, Optional[str], Optional[str]]:
    """Return (welcome_text, welcome_enabled, media_file_id, media_type)."""
    await _ensure_columns()
    cursor = await conn.execute(
        """
        SELECT welcome, welcome_enabled, welcome_media_file_id, welcome_media_type
        FROM groups WHERE chat_id = (?)
        """,
        (chat_id,),
    )
    row = await cursor.fetchone()
    if not row:
        return None, True, None, None
    enabled = row[1]
    if enabled is None:
        enabled = True
    return row[0], bool(enabled), row[2], row[3]


async def set_welcome(
    chat_id: int,
    welcome: Optional[str],
    media_file_id: Optional[str] = None,
    media_type: Optional[str] = None,
):
    """Set welcome text and optional media for a chat."""
    await _ensure_columns()
    # Fetch current row to preserve other columns
    cursor = await conn.execute("SELECT * FROM groups WHERE chat_id = ?", (chat_id,))
    row = await cursor.fetchone()

    if row:
        # Row exists, just update the welcome columns
        await conn.execute(
            """
            UPDATE groups
            SET welcome = ?, welcome_media_file_id = ?, welcome_media_type = ?
            WHERE chat_id = ?
            """,
            (welcome, media_file_id, media_type, chat_id),
        )
    else:
        # Row doesn't exist, create it with defaults
        await conn.execute(
            """
            INSERT INTO groups(
                chat_id, welcome, welcome_enabled, welcome_media_file_id, welcome_media_type
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (chat_id, welcome, True, media_file_id, media_type),
        )
    await conn.commit()


async def toggle_welcome(chat_id: int, mode: bool):
    await _ensure_columns()
    cursor = await conn.execute("SELECT * FROM groups WHERE chat_id = ?", (chat_id,))
    row = await cursor.fetchone()
    if row:
        await conn.execute(
            "UPDATE groups SET welcome_enabled = ? WHERE chat_id = ?",
            (mode, chat_id),
        )
    else:
        await conn.execute(
            "INSERT INTO groups (chat_id, welcome_enabled) VALUES (?, ?)",
            (chat_id, mode),
        )
    await conn.commit()


async def get_goodbye(chat_id: int) -> Tuple[Optional[str], bool, Optional[str], Optional[str]]:
    """Return (goodbye_text, goodbye_enabled, media_file_id, media_type)."""
    await _ensure_columns()
    cursor = await conn.execute(
        """
        SELECT goodbye, goodbye_enabled, goodbye_media_file_id, goodbye_media_type
        FROM groups WHERE chat_id = (?)
        """,
        (chat_id,),
    )
    row = await cursor.fetchone()
    if not row:
        return None, True, None, None
    enabled = row[1]
    if enabled is None:
        enabled = True
    return row[0], bool(enabled), row[2], row[3]


async def set_goodbye(
    chat_id: int,
    goodbye: Optional[str],
    media_file_id: Optional[str] = None,
    media_type: Optional[str] = None,
):
    """Set goodbye text and optional media for a chat."""
    await _ensure_columns()
    cursor = await conn.execute("SELECT * FROM groups WHERE chat_id = ?", (chat_id,))
    row = await cursor.fetchone()

    if row:
        await conn.execute(
            """
            UPDATE groups
            SET goodbye = ?, goodbye_media_file_id = ?, goodbye_media_type = ?
            WHERE chat_id = ?
            """,
            (goodbye, media_file_id, media_type, chat_id),
        )
    else:
        await conn.execute(
            """
            INSERT INTO groups(
                chat_id, goodbye, goodbye_enabled, goodbye_media_file_id, goodbye_media_type
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (chat_id, goodbye, True, media_file_id, media_type),
        )
    await conn.commit()


async def toggle_goodbye(chat_id: int, mode: bool):
    await _ensure_columns()
    cursor = await conn.execute("SELECT * FROM groups WHERE chat_id = ?", (chat_id,))
    row = await cursor.fetchone()
    if row:
        await conn.execute(
            "UPDATE groups SET goodbye_enabled = ? WHERE chat_id = ?",
            (mode, chat_id),
        )
    else:
        await conn.execute(
            "INSERT INTO groups (chat_id, goodbye_enabled) VALUES (?, ?)",
            (chat_id, mode),
        )
    await conn.commit()


async def get_greeting_delete_seconds(chat_id: int) -> int:
    await _ensure_columns()
    cursor = await conn.execute(
        "SELECT greeting_delete_seconds FROM groups WHERE chat_id = ?",
        (chat_id,),
    )
    row = await cursor.fetchone()
    if not row or row[0] is None:
        return await get_default_greeting_delete_seconds()
    return max(0, int(row[0]))


async def set_greeting_delete_seconds(chat_id: int, seconds: int) -> None:
    await _ensure_columns()
    seconds = max(0, min(seconds, 86400))
    cursor = await conn.execute("SELECT chat_id FROM groups WHERE chat_id = ?", (chat_id,))
    row = await cursor.fetchone()
    if row:
        await conn.execute(
            "UPDATE groups SET greeting_delete_seconds = ? WHERE chat_id = ?",
            (seconds, chat_id),
        )
    else:
        await conn.execute(
            "INSERT INTO groups (chat_id, greeting_delete_seconds) VALUES (?, ?)",
            (chat_id, seconds),
        )
    await conn.commit()
