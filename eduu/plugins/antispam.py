# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from html import escape
from re import IGNORECASE, compile, escape as regex_escape

from hydrogram import Client, StopPropagation, filters
from hydrogram.errors import RPCError
from hydrogram.types import ChatPermissions, ChatPrivileges, Message

from config import PREFIXES
from eduu.database.antispam import is_antispam_enabled, set_antispam
from eduu.database.spam_filters import (
    add_spam_filter,
    get_spam_filters,
    remove_spam_filter,
)
from eduu.database.warns import (
    add_warns,
    get_warn_action,
    get_warns,
    get_warns_limit,
    reset_warns,
)
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
telegram_link_pattern = compile(
    r"(?<![\w.])(?:(?:https?://)?(?:t\.me|telegram\.me|telegram\.dog)(?:/\S*)?|tg://\S+)",
    IGNORECASE,
)


def _fingerprint(m: Message) -> str:
    content = m.text or m.caption
    if content:
        return " ".join(content.casefold().split())
    if m.sticker:
        return f"sticker:{m.sticker.file_unique_id}"
    return ""


def _contains_telegram_link(m: Message) -> bool:
    if telegram_link_pattern.search(m.text or m.caption or ""):
        return True
    return any(
        telegram_link_pattern.search(entity.url)
        for entity in (m.entities or []) + (m.caption_entities or [])
        if entity.url
    )


def _is_forwarded(m: Message) -> bool:
    return bool(
        m.forward_from
        or m.forward_sender_name
        or m.forward_from_chat
        or m.forward_from_message_id
        or m.forward_date
    )


def _contains_spam_word(m: Message, spam_words: list[str]) -> bool:
    text = m.text or m.caption or ""
    return any(
        compile(rf"(?<!\w){regex_escape(word)}(?!\w)", IGNORECASE).search(text)
        for word in spam_words
    )


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


async def _moderate_spam(
    c: Client,
    m: Message,
    s: Strings,
    message_ids: list[int],
) -> None:
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


async def _warn_and_delete(c: Client, m: Message, s: Strings, reason: str) -> None:
    try:
        await c.delete_messages(m.chat.id, [m.id])
    except RPCError as error:
        await c.send_message(
            m.chat.id,
            s("antispam_delete_failed").format(
                error=escape(f"{error.__class__.__name__}: {error}")
            ),
        )

    await add_warns(m.chat.id, m.from_user.id, 1)
    warn_count = await get_warns(m.chat.id, m.from_user.id)
    warn_limit = await get_warns_limit(m.chat.id)

    if warn_count >= warn_limit:
        action = await get_warn_action(m.chat.id)
        try:
            if action == "ban":
                await m.chat.ban_member(m.from_user.id)
                text = s("warn_banned")
            elif action == "mute":
                await m.chat.restrict_member(
                    m.from_user.id,
                    ChatPermissions(can_send_messages=False),
                )
                text = s("warn_muted")
            elif action == "kick":
                await m.chat.ban_member(m.from_user.id)
                await m.chat.unban_member(m.from_user.id)
                text = s("warn_kicked")
            else:
                text = s("warn_warned")
        except RPCError as error:
            await c.send_message(
                m.chat.id,
                s("antispam_action_failed").format(
                    error=escape(f"{error.__class__.__name__}: {error}")
                ),
            )
            raise StopPropagation

        warning = text.format(
            target_user=m.from_user.mention,
            warn_count=warn_count,
            warn_limit=warn_limit,
        )
        await reset_warns(m.chat.id, m.from_user.id)
    else:
        warning = s("warn_warned").format(
            target_user=m.from_user.mention,
            warn_count=warn_count,
            warn_limit=warn_limit,
        )

    await c.send_message(
        m.chat.id,
        warning + "\n" + s("warn_reason_text").format(reason_text=reason),
    )
    raise StopPropagation


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


@Client.on_message(filters.command("spamfilter", PREFIXES) & filters.group)
@require_admin(ChatPrivileges(can_delete_messages=True, can_restrict_members=True))
@use_chat_lang
async def add_spam_filter_cmd(c: Client, m: Message, s: Strings):
    parts = m.text.split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        await m.reply_text(s("spam_filter_add_empty"))
        return

    word = parts[1].strip()
    if await add_spam_filter(m.chat.id, word):
        await m.reply_text(s("spam_filter_added").format(word=escape(word)))
    else:
        await m.reply_text(s("spam_filter_exists").format(word=escape(word)))


@Client.on_message(filters.command("delspamfilter", PREFIXES) & filters.group)
@require_admin(ChatPrivileges(can_delete_messages=True, can_restrict_members=True))
@use_chat_lang
async def remove_spam_filter_cmd(c: Client, m: Message, s: Strings):
    parts = m.text.split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        await m.reply_text(s("spam_filter_remove_empty"))
        return

    word = parts[1].strip()
    if await remove_spam_filter(m.chat.id, word):
        await m.reply_text(s("spam_filter_removed").format(word=escape(word)))
    else:
        await m.reply_text(s("spam_filter_not_found").format(word=escape(word)))


@Client.on_message(filters.command("spamfilters", PREFIXES) & filters.group)
@require_admin()
@use_chat_lang
async def list_spam_filters_cmd(c: Client, m: Message, s: Strings):
    spam_words = await get_spam_filters(m.chat.id)
    if not spam_words:
        await m.reply_text(s("spam_filters_empty"))
        return

    words = "\n".join(f" - <code>{escape(word)}</code>" for word in spam_words)
    await m.reply_text(s("spam_filters_list").format(words=words))


@Client.on_message(filters.group & filters.incoming & ~filters.service, group=3)
@use_chat_lang
async def detect_spam(c: Client, m: Message, s: Strings):
    if not await is_antispam_enabled(m.chat.id):
        return

    spam_words = await get_spam_filters(m.chat.id)
    link_spam = _contains_telegram_link(m)
    forward_spam = _is_forwarded(m)
    word_spam = _contains_spam_word(m, spam_words)

    if not m.from_user:
        if link_spam or forward_spam or word_spam:
            try:
                await c.delete_messages(m.chat.id, [m.id])
            except RPCError:
                pass
            raise StopPropagation
        return
    if m.from_user.is_bot:
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

    if link_spam:
        history.clear()
        await _warn_and_delete(c, m, s, s("antispam_reason_telegram_link"))
    if forward_spam:
        history.clear()
        await _warn_and_delete(c, m, s, s("antispam_reason_forward"))
    if word_spam:
        history.clear()
        await _warn_and_delete(c, m, s, s("antispam_reason_spam_word"))
    if not _is_spam(history, now):
        return

    message_ids = [message_id for _, message_id, _ in history]
    history.clear()
    await _moderate_spam(c, m, s, message_ids)


commands.add_command("antispam", "admin_misc")
commands.add_command("delspamfilter", "admin_filters")
commands.add_command("spamfilter", "admin_filters")
commands.add_command("spamfilters", "admin_filters")
