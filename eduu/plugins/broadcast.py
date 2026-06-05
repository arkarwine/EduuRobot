# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from __future__ import annotations

import asyncio
import io
from typing import TYPE_CHECKING

from hydrogram import Client, filters
from hydrogram.errors import BadRequest, Forbidden
from hydrogram.types import Message

from config import LOG_CHAT, PREFIXES
from eduu.database.chat_logs import get_all_chat_ids, get_chat_stats, log_chat
from eduu.utils import sudofilter
from eduu.utils.localization import Strings, use_chat_lang

if TYPE_CHECKING:
    pass


# Log all chats the bot interacts with
@Client.on_message(group=-1)
async def log_all_chats(c: Client, m: Message):
    """Automatically log all chats the bot receives messages from"""
    await log_chat(m.chat, client=c)


@Client.on_message(filters.command("broadcast", PREFIXES) & sudofilter)
@use_chat_lang
async def broadcast_message(c: Client, m: Message, s: Strings):
    """Broadcast a replied message to all logged chats (sudoers only)"""
    if not m.reply_to_message:
        await m.reply_text(
            "Usage: Reply to a message with /broadcast to send it to all chats.\n\n"
            "Example: reply to a message and send /broadcast"
        )
        return

    source_message = m.reply_to_message
    preview_text = source_message.text or source_message.caption or "<i>Media message</i>"

    try:
        chat_ids = await get_all_chat_ids()
        chat_count = len(chat_ids)

        status_msg = await m.reply_text(
            f"<b>Broadcast Message:</b>\n\n{preview_text}\n\n"
            f"<b>ℹ️ This will be sent to {chat_count} chats.</b>\n\n"
            "Broadcasting now..."
        )

        successful = 0
        failed = 0
        errors: str = ""

        for i, chat_id in enumerate(chat_ids):
            try:
                await c.forward_messages(
                    chat_id=chat_id,
                    from_chat_id=source_message.chat.id,
                    message_id=source_message.id,
                )
                successful += 1
            except (BadRequest, Forbidden):
                failed += 1
                errors += f"{chat_id}: {e}\n"

            except Exception as e:
                failed += 1
                errors += f"{chat_id}: {e}\n"

            if (i + 1) % 10 == 0:
                await status_msg.edit_text(
                    f"<b>Broadcasting to {chat_count} chats...</b>\n\n"
                    f"Status: {i + 1}/{chat_count}\n"
                    f"✅ Successful: {successful}\n"
                    f"❌ Failed: {failed}",
                )
                
                await asyncio.sleep(0.1)

        await status_msg.edit_text(
            f"<b>Broadcast Complete!</b>\n\n"
            f"Total chats: {chat_count}\n"
            f"✅ Successful: {successful}\n"
            f"❌ Failed: {failed}",
        )
        if errors:
            file = io.BytesIO(errors.encode("utf-8"))
            file.name = "errors.txt"
            await m.reply_document(file, caption="Errors during broadcast")
    except Exception as e:
        await m.reply_text(f"<b>Error during broadcast:</b>\n<code>{str(e)}</code>")


@Client.on_message(filters.command("chatstats", PREFIXES) & sudofilter)
@use_chat_lang
async def chat_statistics(c: Client, m: Message, s: Strings):
    """Get statistics about logged chats (sudoers only)"""
    try:
        stats = await get_chat_stats()
        all_chats = await get_all_chat_ids()

        stats_text = "<b>Chat Statistics:</b>\n\n"
        stats_text += f"<b>Total chats logged:</b> {len(all_chats)}\n\n"
        stats_text += "<b>Breakdown by type:</b>\n"

        total = 0
        for row in stats:
            chat_type, count = row
            stats_text += f"  • {chat_type}: {count}\n"
            total += count

        await m.reply_text(stats_text)
    except Exception as e:
        print(f"Error getting statistics: {e}")
        await m.reply_text(f"<b>Error getting statistics:</b>\n<code>{str(e)}</code>")
