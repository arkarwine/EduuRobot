# SPDX-License-Identifier: MIT

from __future__ import annotations

import time
from collections import defaultdict, deque
from datetime import datetime, timedelta
from html import escape
from re import IGNORECASE, compile, escape as regex_escape
from urllib.parse import urlparse

from hydrogram import Client, StopPropagation, filters
from hydrogram.errors import RPCError
from hydrogram.types import ChatPrivileges, Message

from config import PREFIXES
from eduu.database.antispam import (
    ALLOWLIST_KINDS,
    add_antispam_allow,
    get_antispam_allowlist,
    get_antispam_settings,
    remove_antispam_allow,
    set_antispam_setting,
)
from eduu.database.spam_filters import add_spam_filter, get_spam_filters, remove_spam_filter
from eduu.utils import commands
from eduu.utils.consts import ADMIN_STATUSES
from eduu.utils.decorators import require_admin
from eduu.utils.localization import Strings, use_chat_lang
from eduu.utils.moderation import (
    add_warning_and_apply_action,
    apply_moderation_action,
    get_missing_bot_permissions,
)

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


def _telegram_links(m: Message) -> set[str]:
    text = m.text or m.caption or ""
    links = set(telegram_link_pattern.findall(text))
    links.update(
        entity.url
        for entity in (m.entities or []) + (m.caption_entities or [])
        if entity.url and telegram_link_pattern.search(entity.url)
    )
    return {link.casefold().rstrip(".,)") for link in links}


def _normalize_link(value: str) -> str:
    value = value.casefold().strip().rstrip("/")
    parsed = urlparse(value if "://" in value else f"https://{value}")
    return (parsed.netloc + parsed.path).strip("/").casefold()


def _is_link_allowed(link: str, allowed: set[str]) -> bool:
    normalized = _normalize_link(link)
    return any(normalized == item or normalized.startswith(f"{item}/") for item in allowed)


def _forward_source(m: Message) -> str | None:
    if m.forward_from_chat:
        return str(m.forward_from_chat.id)
    if m.forward_from:
        return str(m.forward_from.id)
    if m.forward_sender_name:
        return m.forward_sender_name.casefold()
    return None


def _contains_spam_word(m: Message, spam_words: list[str]) -> bool:
    text = m.text or m.caption or ""
    return any(
        compile(rf"(?<!\w){regex_escape(word)}(?!\w)", IGNORECASE).search(text)
        for word in spam_words
    )


def _spam_kind(
    history: deque[tuple[float, int, str]],
    now: float,
    settings: dict[str, bool | int],
) -> str | None:
    if settings["flood"]:
        flood_count = sum(
            timestamp >= now - int(settings["flood_window"]) for timestamp, _, _ in history
        )
        if flood_count >= int(settings["flood_limit"]):
            return "flood"
    if settings["repeats"] and history[-1][2]:
        repeats = sum(
            timestamp >= now - int(settings["repeat_window"])
            and fingerprint == history[-1][2]
            for timestamp, _, fingerprint in history
        )
        if repeats >= int(settings["repeat_limit"]):
            return "repeat"
    return None


def _cleanup_history(now: float, max_window: int) -> None:
    global last_cleanup
    if now - last_cleanup < 60:
        return
    for key, history in list(message_history.items()):
        if not history or history[-1][0] < now - max_window:
            message_history.pop(key, None)
    last_cleanup = now


async def _warn_and_delete(c: Client, m: Message, s: Strings, reason: str) -> None:
    try:
        await c.delete_messages(m.chat.id, [m.id])
    except RPCError as error:
        await c.send_message(
            m.chat.id,
            s("antispam_delete_failed").format(error=escape(f"{type(error).__name__}: {error}")),
        )
    try:
        count, limit, action = await add_warning_and_apply_action(m.chat, m.from_user.id)
    except RPCError as error:
        await c.send_message(
            m.chat.id,
            s("antispam_action_failed").format(error=escape(f"{type(error).__name__}: {error}")),
        )
        raise StopPropagation

    key = {
        "ban": "warn_banned",
        "mute": "warn_muted",
        "kick": "warn_kicked",
        None: "warn_warned",
    }[action]
    warning = s(key).format(
        target_user=m.from_user.mention,
        warn_count=count,
        warn_limit=limit,
    )
    await c.send_message(m.chat.id, warning + "\n" + s("warn_reason_text").format(reason_text=reason))
    raise StopPropagation


async def _mute_spammer(c: Client, m: Message, s: Strings, ids: list[int], minutes: int) -> None:
    try:
        await c.delete_messages(m.chat.id, ids)
        await apply_moderation_action(
            m.chat,
            m.from_user.id,
            "mute",
            until_date=datetime.now() + timedelta(minutes=minutes),
        )
    except RPCError as error:
        await c.send_message(
            m.chat.id,
            s("antispam_action_failed").format(error=escape(f"{type(error).__name__}: {error}")),
        )
        raise StopPropagation
    await c.send_message(
        m.chat.id,
        s("antispam_muted").format(user=m.from_user.mention, minutes=minutes),
    )
    raise StopPropagation


def _settings_text(settings: dict[str, bool | int], s: Strings) -> str:
    enabled = lambda value: s("general_enabled") if value else s("general_disabled")
    return s("antispam_settings").format(
        enabled=enabled(settings["enabled"]),
        links=enabled(settings["links"]),
        forwards=enabled(settings["forwards"]),
        words=enabled(settings["words"]),
        flood=enabled(settings["flood"]),
        repeats=enabled(settings["repeats"]),
        flood_limit=settings["flood_limit"],
        flood_window=settings["flood_window"],
        repeat_limit=settings["repeat_limit"],
        repeat_window=settings["repeat_window"],
        mute_minutes=settings["mute_minutes"],
    )


@Client.on_message(filters.command("antispam", PREFIXES) & filters.group)
@require_admin(ChatPrivileges(can_delete_messages=True, can_restrict_members=True))
@use_chat_lang
async def antispam_settings(c: Client, m: Message, s: Strings):
    settings = await get_antispam_settings(m.chat.id)
    if len(m.command) == 1:
        await m.reply_text(_settings_text(settings, s))
        return

    key = m.command[1].casefold()
    if key != "off":
        missing = await get_missing_bot_permissions(
            m.chat,
            "can_delete_messages",
            "can_restrict_members",
        )
        if missing:
            await m.reply_text(s("bot_missing_permissions").format(permissions=", ".join(missing)))
            return
    if key in {"on", "off"}:
        await set_antispam_setting(m.chat.id, "enabled", key == "on")
    elif key in {"links", "forwards", "words", "flood", "repeats"} and len(m.command) == 3:
        if m.command[2].casefold() not in {"on", "off"}:
            await m.reply_text(s("antispam_invalid_arg"))
            return
        await set_antispam_setting(m.chat.id, key, m.command[2].casefold() == "on")
    elif key in {"flood", "repeat"} and len(m.command) == 4:
        try:
            limit, window = int(m.command[2]), int(m.command[3])
        except ValueError:
            await m.reply_text(s("antispam_invalid_arg"))
            return
        if not 2 <= limit <= 50 or not 2 <= window <= 300:
            await m.reply_text(s("antispam_invalid_arg"))
            return
        await set_antispam_setting(m.chat.id, f"{key}_limit", limit)
        await set_antispam_setting(m.chat.id, f"{key}_window", window)
    elif key == "mute" and len(m.command) == 3 and m.command[2].isdigit():
        await set_antispam_setting(m.chat.id, "mute_minutes", min(max(int(m.command[2]), 1), 1440))
    else:
        await m.reply_text(s("antispam_invalid_arg"))
        return

    if key == "off":
        for history_key in [item for item in message_history if item[0] == m.chat.id]:
            message_history.pop(history_key, None)
    await m.reply_text(_settings_text(await get_antispam_settings(m.chat.id), s))


@Client.on_message(filters.command(["spamallow", "delspamallow"], PREFIXES) & filters.group)
@require_admin(ChatPrivileges(can_delete_messages=True, can_restrict_members=True))
@use_chat_lang
async def edit_spam_allowlist(c: Client, m: Message, s: Strings):
    if len(m.command) < 3 or m.command[1].casefold() not in ALLOWLIST_KINDS:
        await m.reply_text(s("spam_allow_help"))
        return
    kind, value = m.command[1].casefold(), " ".join(m.command[2:]).strip()
    if kind == "user":
        value = value.lstrip("@")
    elif kind == "link":
        value = _normalize_link(value)
    changed = (
        await remove_antispam_allow(m.chat.id, kind, value)
        if m.command[0].casefold() == "delspamallow"
        else await add_antispam_allow(m.chat.id, kind, value)
    )
    await m.reply_text(
        s("spam_allow_changed" if changed else "spam_allow_unchanged").format(
            kind=kind, value=escape(value)
        )
    )


@Client.on_message(filters.command("spamallowlist", PREFIXES) & filters.group)
@require_admin()
@use_chat_lang
async def list_spam_allowlist(c: Client, m: Message, s: Strings):
    allowed = await get_antispam_allowlist(m.chat.id)
    lines = [
        f"<b>{kind}</b>: " + (", ".join(f"<code>{escape(v)}</code>" for v in sorted(values)) or "-")
        for kind, values in sorted(allowed.items())
    ]
    await m.reply_text(s("spam_allow_list").format(items="\n".join(lines)))


@Client.on_message(filters.command("spamfilter", PREFIXES) & filters.group)
@require_admin(ChatPrivileges(can_delete_messages=True, can_restrict_members=True))
@use_chat_lang
async def add_spam_filter_cmd(c: Client, m: Message, s: Strings):
    parts = m.text.split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        await m.reply_text(s("spam_filter_add_empty"))
        return
    word = parts[1].strip()
    key = "spam_filter_added" if await add_spam_filter(m.chat.id, word) else "spam_filter_exists"
    await m.reply_text(s(key).format(word=escape(word)))


@Client.on_message(filters.command("delspamfilter", PREFIXES) & filters.group)
@require_admin(ChatPrivileges(can_delete_messages=True, can_restrict_members=True))
@use_chat_lang
async def remove_spam_filter_cmd(c: Client, m: Message, s: Strings):
    parts = m.text.split(None, 1)
    if len(parts) < 2 or not parts[1].strip():
        await m.reply_text(s("spam_filter_remove_empty"))
        return
    word = parts[1].strip()
    key = "spam_filter_removed" if await remove_spam_filter(m.chat.id, word) else "spam_filter_not_found"
    await m.reply_text(s(key).format(word=escape(word)))


@Client.on_message(filters.command("spamfilters", PREFIXES) & filters.group)
@require_admin()
@use_chat_lang
async def list_spam_filters_cmd(c: Client, m: Message, s: Strings):
    words = await get_spam_filters(m.chat.id)
    if not words:
        await m.reply_text(s("spam_filters_empty"))
        return
    await m.reply_text(s("spam_filters_list").format(words="\n".join(f" - <code>{escape(w)}</code>" for w in words)))


@Client.on_message(filters.group & filters.incoming & ~filters.service, group=3)
@use_chat_lang
async def detect_spam(c: Client, m: Message, s: Strings):
    settings = await get_antispam_settings(m.chat.id)
    if not settings["enabled"]:
        return
    allowed = await get_antispam_allowlist(m.chat.id)
    user_values = {str(m.from_user.id), (m.from_user.username or "").casefold()} if m.from_user else set()
    if user_values & allowed["user"]:
        return

    links = _telegram_links(m)
    link_spam = bool(settings["links"] and links and not all(_is_link_allowed(link, allowed["link"]) for link in links))
    source = _forward_source(m)
    forward_spam = bool(settings["forwards"] and source and source.casefold() not in allowed["source"])
    word_spam = bool(settings["words"] and _contains_spam_word(m, await get_spam_filters(m.chat.id)))

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
        if (await m.chat.get_member(m.from_user.id)).status in ADMIN_STATUSES:
            return
    except RPCError:
        return

    now = time.monotonic()
    max_window = max(int(settings["flood_window"]), int(settings["repeat_window"]))
    _cleanup_history(now, max_window)
    history = message_history[(m.chat.id, m.from_user.id)]
    while history and history[0][0] < now - max_window:
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
    if not _spam_kind(history, now, settings):
        return
    ids = [message_id for _, message_id, _ in history]
    history.clear()
    await _mute_spammer(c, m, s, ids, int(settings["mute_minutes"]))


for command in ("antispam", "spamallow", "delspamallow", "spamallowlist", "spamfilter", "delspamfilter", "spamfilters"):
    commands.add_command(command, "admin_antispam")
