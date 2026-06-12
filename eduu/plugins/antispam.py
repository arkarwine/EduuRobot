# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from html import escape

from hydrogram import Client, StopPropagation, filters
from hydrogram.errors import RPCError
from hydrogram.types import ChatPermissions, ChatPrivileges, Message

from config import PREFIXES
from eduu.database.antispam import is_antispam_enabled, set_antispam
from eduu.utils import commands
from eduu.utils.consts import ADMIN_STATUSES
from eduu.utils.decorators import require_admin
from eduu.utils.localization import Strings, use_chat_lang

FLOOD_LIMIT = 6
FLOOD_WINDOW = 8
REPEAT_LIMIT = 3
REPEAT_WINDOW = 20
MUTE_MINUTES = 5

message_history: dict[tuple[int, int], deque[tuple[float, int, str]]] = defaultdict(deque)
last_cleanup = 0.0


def _fingerprint(m: Message) -> str:
    content = m.text or m.caption
    if content:
        return " ".join(content.casefold().split())
    if m.sticker:
        return f"sticker:{m.sticker.file_unique_id}"
    return ""


def _is_spam(history: deque[tuple[float, int, str]], now: float) -> bool:
    flood_count = sum(timestamp >= now - FLOOD_WINDOW for timestamp, _, _ in history)
    if flood_count >= FLOOD_LIMIT:
        return True

    latest_fingerprint = history[-1][2]
    if not latest_fingerprint:
        return False
    repeat_count = sum(
        timestamp >= now - REPEAT_WINDOW and fingerprint == latest_fingerprint
        for timestamp, _, fingerprint in history
    )
    return repeat_count >= REPEAT_LIMIT


def _cleanup_history(now: float) -> None:
    global last_cleanup

    if now - last_cleanup < 60:
        return
    for key, history in list(message_history.items()):
        if not history or history[-1][0] < now - REPEAT_WINDOW:
            message_history.pop(key, None)
    last_cleanup = now


@Client.on_message(filters.command("antispam", PREFIXES) & filters.group)
@require_admin(ChatPrivileges(can_delete_messages=True, can_restrict_members=True))
@use_chat_lang
async def antispam_settings(c: Client, m: Message, s: Strings):
    if len(m.command) == 1:
        key = (
            "antispam_status_enabled"
            if await is_antispam_enabled(m.chat.id)
            else "antispam_status_disabled"
        )
        await m.reply_text(s(key))
        return

    mode = m.command[1].lower()
    if mode not in {"on", "off"}:
        await m.reply_text(s("antispam_invalid_arg"))
        return

    enabled = mode == "on"
    await set_antispam(m.chat.id, enabled)
    if not enabled:
        for key in [key for key in message_history if key[0] == m.chat.id]:
            message_history.pop(key, None)
    await m.reply_text(s("antispam_enabled" if enabled else "antispam_disabled"))


@Client.on_message(filters.group & filters.incoming & ~filters.service, group=3)
@use_chat_lang
async def detect_spam(c: Client, m: Message, s: Strings):
    if not m.from_user or m.from_user.is_bot or not await is_antispam_enabled(m.chat.id):
        return

    try:
        member = await m.chat.get_member(m.from_user.id)
    except RPCError:
        return
    if member.status in ADMIN_STATUSES:
        return

    now = time.monotonic()
    _cleanup_history(now)
    key = (m.chat.id, m.from_user.id)
    history = message_history[key]
    while history and history[0][0] < now - REPEAT_WINDOW:
        history.popleft()
    history.append((now, m.id, _fingerprint(m)))

    if not _is_spam(history, now):
        return

    message_ids = [message_id for _, message_id, _ in history]
    history.clear()

    try:
        await c.delete_messages(m.chat.id, message_ids)
    except RPCError:
        pass

    try:
        await m.chat.restrict_member(
            m.from_user.id,
            ChatPermissions(can_send_messages=False),
            until_date=datetime.now() + timedelta(minutes=MUTE_MINUTES),
        )
    except RPCError as error:
        await c.send_message(
            m.chat.id,
            s("antispam_action_failed").format(
                error=escape(f"{error.__class__.__name__}: {error}")
            ),
        )
        raise StopPropagation

    await c.send_message(
        m.chat.id,
        s("antispam_muted").format(
            user=m.from_user.mention,
            minutes=MUTE_MINUTES,
        ),
    )
    raise StopPropagation


commands.add_command("antispam", "admin_misc")
