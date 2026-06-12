# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from __future__ import annotations

import asyncio
from html import escape

from hydrogram import Client, filters
from hydrogram.errors import FloodWait
from hydrogram.types import Message

from config import PREFIXES
from eduu.utils import commands
from eduu.utils.decorators import require_admin
from eduu.utils.localization import Strings, use_chat_lang

BATCH_SIZE = 5
BATCH_DELAY = 2
MAX_HEADING_LENGTH = 2000

mention_tasks: dict[int, asyncio.Task] = {}


def _get_heading(m: Message, s: Strings) -> str:
    parts = m.text.split(None, 1)
    if len(parts) > 1:
        return escape(parts[1][:MAX_HEADING_LENGTH])
    if m.reply_to_message:
        reply_text = m.reply_to_message.text or m.reply_to_message.caption
        if reply_text:
            return escape(reply_text[:MAX_HEADING_LENGTH])
    return s("mention_all_default_heading")


async def _send_batch(c: Client, chat_id: int, text: str) -> None:
    while True:
        try:
            await c.send_message(chat_id, text)
            return
        except FloodWait as error:
            await asyncio.sleep(error.value)


async def _mention_members(c: Client, m: Message, s: Strings, heading: str) -> None:
    mentions: list[str] = []
    mentioned = 0

    try:
        async for member in m.chat.get_members():
            user = member.user
            if not user or user.is_bot or user.is_deleted:
                continue

            mentions.append(user.mention)
            if len(mentions) < BATCH_SIZE:
                continue

            await _send_batch(c, m.chat.id, f"{heading}\n\n{' '.join(mentions)}")
            mentioned += len(mentions)
            mentions.clear()
            await asyncio.sleep(BATCH_DELAY)

        if mentions:
            await _send_batch(c, m.chat.id, f"{heading}\n\n{' '.join(mentions)}")
            mentioned += len(mentions)

        if mentioned == 0:
            await c.send_message(m.chat.id, s("mention_all_no_members"))
        else:
            await c.send_message(m.chat.id, s("mention_all_complete").format(count=mentioned))
    except asyncio.CancelledError:
        await c.send_message(m.chat.id, s("mention_all_cancelled"))
        raise
    except Exception as error:
        await c.send_message(
            m.chat.id,
            s("mention_all_failed").format(
                error=escape(f"{error.__class__.__name__}: {error}")
            ),
        )
    finally:
        mention_tasks.pop(m.chat.id, None)


@Client.on_message(
    (
        filters.command(["all", "tagall", "mentionall"], PREFIXES)
        | filters.regex(r"^@(all|everyone)\b")
    )
    & filters.group
)
@require_admin()
@use_chat_lang
async def mention_all(c: Client, m: Message, s: Strings):
    current_task = mention_tasks.get(m.chat.id)
    if current_task and not current_task.done():
        await m.reply_text(s("mention_all_already_running"))
        return

    task = asyncio.create_task(_mention_members(c, m, s, _get_heading(m, s)))
    mention_tasks[m.chat.id] = task
    await m.reply_text(s("mention_all_started"))


@Client.on_message(filters.command("cancelall", PREFIXES) & filters.group)
@require_admin()
@use_chat_lang
async def cancel_mention_all(c: Client, m: Message, s: Strings):
    task = mention_tasks.get(m.chat.id)
    if not task or task.done():
        await m.reply_text(s("mention_all_not_running"))
        return

    task.cancel()


commands.add_command("all", "admin_misc")
commands.add_command("cancelall", "admin_misc")
