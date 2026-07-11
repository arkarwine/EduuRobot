# SPDX-License-Identifier: MIT

from __future__ import annotations

from .core import database


async def get_sudo_overrides() -> dict[int, bool]:
    conn = database.get_conn()
    cursor = await conn.execute("SELECT user_id, enabled FROM sudoers")
    rows = await cursor.fetchall()
    await cursor.close()
    return {int(row[0]): bool(row[1]) for row in rows}


async def set_sudo_override(user_id: int, enabled: bool, updated_by: int) -> None:
    conn = database.get_conn()
    await conn.execute(
        """
        INSERT INTO sudoers(user_id, enabled, updated_by, updated_at)
        VALUES(?, ?, ?, CURRENT_TIMESTAMP)
        ON CONFLICT(user_id) DO UPDATE SET
            enabled = excluded.enabled,
            updated_by = excluded.updated_by,
            updated_at = CURRENT_TIMESTAMP
        """,
        (user_id, int(enabled), updated_by),
    )
    await conn.commit()
