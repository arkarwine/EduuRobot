# SPDX-License-Identifier: MIT

from __future__ import annotations

import asyncio
from html import escape

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
mention_tasks: dict[int, asyncio.Task] = {}


def _get_heading(m: Message, s: Strings) -> str:
    parts = m.text.split(None, 1)
    if len(parts) > 1:
        return escape(parts[1][:MAX_HEADING_LENGTH])
    if m.reply_to_message:
        text = m.reply_to_message.text or m.reply_to_message.caption
        if text:
            return escape(text[:MAX_HEADING_LENGTH])
    return s("mention_all_default_heading")


def _mention(user, settings: dict[str, bool | int | str]) -> str:
    if settings["hidden"]:
        return f'<a href="tg://user?id={user.id}">{escape(str(settings["emoji"]))}</a>'
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
) -> None:
    mentions: list[str] = []
    mentioned = 0
    batch_size = int(settings["batch_size"])
    delay = int(settings["delay_seconds"])
    try:
        async for member in m.chat.get_members():
            user = member.user
            if not user or user.is_bot or user.is_deleted:
                continue
            if not settings["include_admins"] and member.status in ADMIN_STATUSES:
                continue
            mentions.append(_mention(user, settings))
            if len(mentions) < batch_size:
                continue
            await _send_batch(c, m.chat.id, f"{heading}\n\n{' '.join(mentions)}")
            mentioned += len(mentions)
            mentions.clear()
            await asyncio.sleep(delay)
        if mentions:
            await _send_batch(c, m.chat.id, f"{heading}\n\n{' '.join(mentions)}")
            mentioned += len(mentions)
        key = "mention_all_complete" if mentioned else "mention_all_no_members"
        await c.send_message(m.chat.id, s(key).format(count=mentioned))
    except asyncio.CancelledError:
        await c.send_message(m.chat.id, s("mention_all_cancelled"))
        raise
    except Exception as error:
        await c.send_message(
            m.chat.id,
            s("mention_all_failed").format(error=escape(f"{type(error).__name__}: {error}")),
        )
    finally:
        mention_tasks.pop(m.chat.id, None)


@Client.on_message(
    (filters.command(["all", "tagall", "mentionall"], PREFIXES) | filters.regex(r"^@(all|everyone)\b"))
    & filters.group
)
@require_admin()
@use_chat_lang
async def mention_all(c: Client, m: Message, s: Strings):
    task = mention_tasks.get(m.chat.id)
    if task and not task.done():
        await m.reply_text(s("mention_all_already_running"))
        return
    try:
        if (await m.chat.get_member("me")).status not in ADMIN_STATUSES:
            await m.reply_text(s("mention_all_bot_must_be_admin"))
            return
    except RPCError as error:
        await m.reply_text(s("mention_all_failed").format(error=escape(str(error))))
        return
    settings = await get_mention_settings(m.chat.id)
    mention_tasks[m.chat.id] = asyncio.create_task(
        _mention_members(c, m, s, _get_heading(m, s), settings)
    )
    await m.reply_text(s("mention_all_started"))


@Client.on_message(filters.command(["cancelall", "stopall"], PREFIXES) & filters.group)
@require_admin()
@use_chat_lang
async def cancel_mention_all(c: Client, m: Message, s: Strings):
    task = mention_tasks.get(m.chat.id)
    if not task or task.done():
        await m.reply_text(s("mention_all_not_running"))
        return
    task.cancel()
    await m.reply_text(s("mention_all_stop_requested"))


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
            emoji=escape(str(settings["emoji"])),
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
    elif key == "emoji" and 1 <= len(value) <= 16:
        await set_mention_setting(m.chat.id, "emoji", value)
    else:
        await m.reply_text(s("mention_all_config_help"))
        return
    await m.reply_text(s("mention_all_config_updated"))


for command in ("all", "stopall", "allstatus", "setall"):
    commands.add_command(command, "admin_mentions")
