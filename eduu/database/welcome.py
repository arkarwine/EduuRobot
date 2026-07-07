# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from __future__ import annotations

from typing import Optional, Tuple

from .core import database

conn = database.get_conn()


async def _ensure_columns():
    """Attempt to add welcome/goodbye columns if they don't exist."""
    columns = {
        "welcome_media_file_id": "TEXT",
        "welcome_media_type": "TEXT",
        "goodbye": "TEXT",
        "goodbye_enabled": "INTEGER",
        "goodbye_media_file_id": "TEXT",
        "goodbye_media_type": "TEXT",
    }
    for column, column_type in columns.items():
        try:
            await conn.execute(f"ALTER TABLE groups ADD COLUMN {column} {column_type}")
            await conn.commit()
        except Exception:
            pass


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
