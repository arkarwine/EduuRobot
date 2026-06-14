# SPDX-License-Identifier: MIT

from __future__ import annotations

import asyncio
from html import escape
from random import choice

from hydrogram import Client, filters
from hydrogram.errors import FloodWait, RPCError
from hydrogram.types import Message

from config import PREFIXES
from eduu.database.mention_all import get_mention_settings, set_mention_setting
from eduu.utils import commands
from eduu.utils.consts import ADMIN_STATUSES
from eduu.utils.decorators import require_admin
from eduu.utils.localization import Strings, use_chat_lang

MAX_HEADING_LENGTH = 2000
MAX_CALL_MEMBERS = 1000
DEFAULT_CALL_MEMBERS = 100
MENTION_EMOJIS = ("🔔", "✨", "📣", "👋", "💬", "⚡", "🎯", "📌", "🌟", "🙌")
mention_tasks: dict[int, asyncio.Task] = {}


def _heading_from_text_or_reply(m: Message, text: str = "") -> str | None:
    if text.strip():
        return escape(text.strip()[:MAX_HEADING_LENGTH])
    if m.reply_to_message:
        reply_text = m.reply_to_message.text or m.reply_to_message.caption
        if reply_text:
            return escape(reply_text[:MAX_HEADING_LENGTH])
    return None


def _command_text(m: Message) -> str:
    parts = m.text.split(None, 1)
    return parts[1] if len(parts) > 1 else ""


def _parse_call(m: Message, default_batch: int) -> tuple[int, int, str | None]:
    parts = _command_text(m).split()
    amount = DEFAULT_CALL_MEMBERS
    batch = default_batch
    if parts and parts[0].isdigit():
        amount = min(max(int(parts.pop(0)), 1), MAX_CALL_MEMBERS)
    if parts and parts[0].isdigit():
        batch = min(max(int(parts.pop(0)), 1), 20)
    return amount, batch, _heading_from_text_or_reply(m, " ".join(parts))


def _mention(user, hidden: bool) -> str:
    if hidden:
        return f'<a href="tg://user?id={user.id}">{choice(MENTION_EMOJIS)}</a>'
    return user.mention


async def _send_batch(c: Client, chat_id: int, text: str) -> None:
    while True:
        try:
            await c.send_message(chat_id, text)
            return
        except FloodWait as error:
            await asyncio.sleep(error.value)


async def _mention_members(
    c: Client,
    m: Message,
    s: Strings,
    heading: str,
    settings: dict[str, bool | int | str],
    *,
    member_limit: int | None = None,
    batch_size: int | None = None,
    admins_only: bool = False,
) -> None:
    mentions: list[str] = []
    mentioned = 0
    batch_size = batch_size or int(settings["batch_size"])
    delay = int(settings["delay_seconds"])
    current_task = asyncio.current_task()
    try:
        async for member in m.chat.get_members():
            user = member.user
            if not user or user.is_bot or user.is_deleted:
                continue
            if admins_only and member.status not in ADMIN_STATUSES:
                continue
            if not admins_only and not settings["include_admins"] and member.status in ADMIN_STATUSES:
                continue
            mentions.append(_mention(user, bool(settings["hidden"])))
            mentioned += 1
            if len(mentions) >= batch_size:
                await _send_batch(c, m.chat.id, f"{heading}\n\n{' '.join(mentions)}")
                mentions.clear()
                if member_limit is None or mentioned < member_limit:
                    await asyncio.sleep(delay)
            if member_limit is not None and mentioned >= member_limit:
                break

        if mentions:
            await _send_batch(c, m.chat.id, f"{heading}\n\n{' '.join(mentions)}")
        key = "mention_all_complete" if mentioned else "mention_all_no_members"
        await c.send_message(m.chat.id, s(key).format(count=mentioned))
    except asyncio.CancelledError:
        raise
    except Exception as error:
        await c.send_message(
            m.chat.id,
            s("mention_all_failed").format(error=escape(f"{type(error).__name__}: {error}")),
        )
    finally:
        if mention_tasks.get(m.chat.id) is current_task:
            mention_tasks.pop(m.chat.id, None)


async def _start_call(
    c: Client,
    m: Message,
    s: Strings,
    heading: str | None,
    *,
    member_limit: int | None = None,
    batch_size: int | None = None,
    admins_only: bool = False,
) -> None:
    task = mention_tasks.get(m.chat.id)
    if task and not task.done():
        await m.reply_text(s("mention_all_already_running"))
        return
    if not heading:
        await m.reply_text(s("mention_all_text_required"))
        return
    try:
        if (await m.chat.get_member("me")).status not in ADMIN_STATUSES:
            await m.reply_text(s("mention_all_bot_must_be_admin"))
            return
    except RPCError as error:
        await m.reply_text(s("mention_all_failed").format(error=escape(str(error))))
        return

    settings = await get_mention_settings(m.chat.id)
    task = asyncio.create_task(
        _mention_members(
            c,
            m,
            s,
            heading,
            settings,
            member_limit=member_limit,
            batch_size=batch_size,
            admins_only=admins_only,
        )
    )
    mention_tasks[m.chat.id] = task
    await m.reply_text(s("mention_all_started"))


@Client.on_message(filters.command(["all", "callall"], PREFIXES) & filters.group)
@require_admin()
@use_chat_lang
async def call_all(c: Client, m: Message, s: Strings):
    await _start_call(c, m, s, _heading_from_text_or_reply(m, _command_text(m)))


@Client.on_message(filters.command(["call", "callactive", "active"], PREFIXES) & filters.group)
@require_admin()
@use_chat_lang
async def configurable_call(c: Client, m: Message, s: Strings):
    settings = await get_mention_settings(m.chat.id)
    amount, batch, heading = _parse_call(m, int(settings["batch_size"]))
    await _start_call(c, m, s, heading, member_limit=amount, batch_size=batch)


@Client.on_message(filters.command(["calladmins", "tagadmins"], PREFIXES) & filters.group)
@require_admin()
@use_chat_lang
async def call_admins(c: Client, m: Message, s: Strings):
    await _start_call(
        c,
        m,
        s,
        _heading_from_text_or_reply(m, _command_text(m)),
        admins_only=True,
    )


@Client.on_message(filters.command("anybody", PREFIXES) & filters.group)
@require_admin()
@use_chat_lang
async def call_anybody(c: Client, m: Message, s: Strings):
    heading = _heading_from_text_or_reply(m, _command_text(m))
    if not heading:
        await m.reply_text(s("mention_all_text_required"))
        return
    members = [
        member.user
        async for member in m.chat.get_members()
        if member.user and not member.user.is_bot and not member.user.is_deleted
    ]
    if not members:
        await m.reply_text(s("mention_all_no_members"))
        return
    await m.reply_text(f"{heading}\n\n{_mention(choice(members), True)}")


@Client.on_message(
    filters.command(["stopcall", "stop"], PREFIXES) & filters.group
)
@require_admin()
@use_chat_lang
async def cancel_mention_all(c: Client, m: Message, s: Strings):
    task = mention_tasks.get(m.chat.id)
    if not task or task.done():
        mention_tasks.pop(m.chat.id, None)
        await m.reply_text(s("mention_all_not_running"))
        return
    status_message = await m.reply_text(s("mention_all_stop_requested"))
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    await status_message.edit_text(s("mention_all_cancelled"))


@Client.on_message(filters.command("allstatus", PREFIXES) & filters.group)
@require_admin()
@use_chat_lang
async def mention_all_status(c: Client, m: Message, s: Strings):
    settings = await get_mention_settings(m.chat.id)
    running = bool((task := mention_tasks.get(m.chat.id)) and not task.done())
    await m.reply_text(
        s("mention_all_settings").format(
            running=s("general_yes") if running else s("general_no"),
            batch=settings["batch_size"],
            delay=settings["delay_seconds"],
            hidden=s("general_yes") if settings["hidden"] else s("general_no"),
            admins=s("general_yes") if settings["include_admins"] else s("general_no"),
        )
    )


@Client.on_message(filters.command("setall", PREFIXES) & filters.group)
@require_admin()
@use_chat_lang
async def configure_mention_all(c: Client, m: Message, s: Strings):
    if len(m.command) < 3:
        await m.reply_text(s("mention_all_config_help"))
        return
    key, value = m.command[1].casefold(), " ".join(m.command[2:]).strip()
    if key == "batch" and value.isdigit() and 1 <= int(value) <= 20:
        await set_mention_setting(m.chat.id, "batch_size", int(value))
    elif key == "delay" and value.isdigit() and 1 <= int(value) <= 30:
        await set_mention_setting(m.chat.id, "delay_seconds", int(value))
    elif key in {"hidden", "admins"} and value.casefold() in {"on", "off"}:
        db_key = "hidden" if key == "hidden" else "include_admins"
        await set_mention_setting(m.chat.id, db_key, value.casefold() == "on")
    else:
        await m.reply_text(s("mention_all_config_help"))
        return
    await m.reply_text(s("mention_all_config_updated"))


for command in ("all", "call", "calladmins", "anybody", "stop", "allstatus", "setall"):
    commands.add_command(command, "mentions")
