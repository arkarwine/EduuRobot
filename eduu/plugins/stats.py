# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from __future__ import annotations

import time
from html import escape

import humanfriendly
from hydrogram import Client, filters
from hydrogram.types import Message

from config import PREFIXES
from eduu.database import database
from eduu.utils import commands
from eduu.utils.localization import Strings, use_chat_lang

conn = database.get_conn()


async def _count_table(table: str) -> int:
    try:
        cursor = await conn.execute(f"SELECT COUNT(*) FROM {table}")
        row = await cursor.fetchone()
    except Exception:
        return 0
    return int(row[0] or 0)


async def _chat_log_total() -> int:
    cursor = await conn.execute("SELECT COUNT(*) FROM chat_logs")
    row = await cursor.fetchone()
    return int(row[0] or 0)


async def _chat_log_breakdown() -> dict[str, int]:
    cursor = await conn.execute(
        "SELECT chat_type, COUNT(*) FROM chat_logs GROUP BY chat_type",
    )
    rows = await cursor.fetchall()
    breakdown: dict[str, int] = {}
    for row in rows:
        chat_type = _normalize_chat_type(row[0])
        breakdown[chat_type] = breakdown.get(chat_type, 0) + int(row[1] or 0)
    return breakdown


async def _recent_chat_count(window: str) -> int:
    cursor = await conn.execute(
        """
        SELECT COUNT(*)
        FROM chat_logs
        WHERE last_seen >= datetime('now', ?)
        """,
        (window,),
    )
    row = await cursor.fetchone()
    return int(row[0] or 0)


def _normalize_chat_type(chat_type: str | None) -> str:
    text = str(chat_type or "unknown")
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    return text.lower()


def _fmt(value: int) -> str:
    return f"{value:,}"


@Client.on_message(filters.command("stats", PREFIXES))
@use_chat_lang
async def bot_reach_stats(c: Client, m: Message, s: Strings) -> None:
    try:
        total_logged = await _chat_log_total()
        breakdown = await _chat_log_breakdown()
        users = await _count_table("users")
        groups = await _count_table("groups")
        channels = await _count_table("channels")
        filters_count = await _count_table("filters")
        notes_count = await _count_table("notes")

        active_24h = await _recent_chat_count("-1 day")
        active_7d = await _recent_chat_count("-7 days")
        active_30d = await _recent_chat_count("-30 days")

        private_logged = breakdown.get("private", 0)
        group_logged = breakdown.get("group", 0) + breakdown.get("supergroup", 0)
        channel_logged = breakdown.get("channel", 0)
        other_logged = max(total_logged - private_logged - group_logged - channel_logged, 0)

        uptime = humanfriendly.format_timespan(round(time.time() - c.start_time))
        text = s("stats_reach").format(
            total_logged=_fmt(total_logged),
            private_logged=_fmt(private_logged),
            group_logged=_fmt(group_logged),
            channel_logged=_fmt(channel_logged),
            other_logged=_fmt(other_logged),
            active_24h=_fmt(active_24h),
            active_7d=_fmt(active_7d),
            active_30d=_fmt(active_30d),
            users=_fmt(users),
            groups=_fmt(groups),
            channels=_fmt(channels),
            filters=_fmt(filters_count),
            notes=_fmt(notes_count),
            uptime=escape(uptime),
        )
        await m.reply_text(text)
    except Exception as e:
        await m.reply_text(s("stats_error").format(error=escape(str(e))))


commands.add_command("stats", "tools")
