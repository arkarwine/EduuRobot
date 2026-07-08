# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from __future__ import annotations

import asyncio
import io
from html import escape
from time import time
from uuid import uuid4

from hydrogram import Client, filters
from hydrogram.errors import BadRequest, FloodWait, Forbidden
from hydrogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from config import LOG_CHAT, PREFIXES
from eduu.database.chat_logs import (
    get_all_chat_ids,
    get_chat_stats,
    get_private_broadcast_chat_ids,
    log_chat,
)
from eduu.utils import commands, sudofilter
from eduu.utils.buttons import styled_button
from eduu.utils.localization import Strings, use_chat_lang
from eduu.utils.styled_messages import edit_styled_text, send_styled_text

BROADCAST_BATCH_SIZE = 10
BROADCAST_BATCH_DELAY_SECONDS = 0.5
BROADCAST_PREVIEW_LIMIT = 700
BROADCAST_PENDING_TTL = 15 * 60

pending_broadcasts: dict[str, dict[str, int | str | list[int] | float]] = {}


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
        await m.reply_text(s("broadcast_usage"))
        return

    source_message = m.reply_to_message
    preview_text = source_message.text or source_message.caption or s("broadcast_media_preview")
    preview_text = escape(preview_text)
    if len(preview_text) > BROADCAST_PREVIEW_LIMIT:
        preview_text = f"{preview_text[:BROADCAST_PREVIEW_LIMIT]}..."

    try:
        chat_ids = await get_private_broadcast_chat_ids()
        chat_count = len(chat_ids)
        if chat_count == 0:
            await m.reply_text(s("broadcast_no_targets"))
            return

        token = uuid4().hex
        pending_broadcasts[token] = {
            "requester_id": m.from_user.id,
            "source_chat_id": source_message.chat.id,
            "source_message_id": source_message.id,
            "chat_ids": chat_ids,
            "created_at": time(),
        }

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    styled_button(
                        s("broadcast_confirm_btn"),
                        callback_data=f"broadcast:confirm:{token}",
                        style="danger",
                    ),
                    styled_button(
                        s("cancel_action_btn"),
                        callback_data=f"broadcast:cancel:{token}",
                        style="secondary",
                    ),
                ]
            ]
        )
        await send_styled_text(
            m,
            s("broadcast_preview").format(count=chat_count, preview=preview_text),
            keyboard,
        )
    except Exception as e:
        await m.reply_text(s("broadcast_failed").format(error=escape(str(e))))


async def _forward_to_chat(
    c: Client,
    chat_id: int,
    source_chat_id: int,
    source_message_id: int,
) -> tuple[bool, str | None]:
    while True:
        try:
            await c.forward_messages(
                chat_id=chat_id,
                from_chat_id=source_chat_id,
                message_ids=[source_message_id],
            )
            return True, None
        except FloodWait as e:
            await asyncio.sleep(e.value)
        except (BadRequest, Forbidden) as e:
            return False, f"{chat_id}: {e}\n"
        except Exception as e:
            return False, f"{chat_id}: {e}\n"


@Client.on_callback_query(filters.regex(r"^broadcast:(confirm|cancel):"))
@use_chat_lang
async def confirm_broadcast(c: Client, m: CallbackQuery, s: Strings):
    action, token = m.data.split(":")[1:3]
    pending = pending_broadcasts.get(token)
    if not pending:
        await m.answer()
        await edit_styled_text(m.message, s("broadcast_expired"), None)
        return
    if pending["requester_id"] != m.from_user.id:
        await m.answer(s("broadcast_wrong_user"), show_alert=True)
        return

    pending_broadcasts.pop(token, None)
    await m.answer()
    if action == "cancel":
        await edit_styled_text(m.message, s("broadcast_cancelled"), None)
        return
    if time() - float(pending["created_at"]) > BROADCAST_PENDING_TTL:
        await edit_styled_text(m.message, s("broadcast_expired"), None)
        return

    chat_ids = list(pending["chat_ids"])
    chat_count = len(chat_ids)
    successful = 0
    failed = 0
    errors = ""
    source_chat_id = int(pending["source_chat_id"])
    source_message_id = int(pending["source_message_id"])

    await edit_styled_text(
        m.message,
        s("broadcast_started").format(count=chat_count),
        None,
    )

    try:
        for start in range(0, chat_count, BROADCAST_BATCH_SIZE):
            batch = chat_ids[start : start + BROADCAST_BATCH_SIZE]
            results = await asyncio.gather(
                *(
                    _forward_to_chat(c, chat_id, source_chat_id, source_message_id)
                    for chat_id in batch
                )
            )
            for sent, error in results:
                if sent:
                    successful += 1
                else:
                    failed += 1
                    errors += error or ""

            completed = min(start + len(batch), chat_count)
            await edit_styled_text(
                m.message,
                s("broadcast_progress").format(
                    completed=completed,
                    total=chat_count,
                    successful=successful,
                    failed=failed,
                    delay=BROADCAST_BATCH_DELAY_SECONDS,
                ),
                None,
            )

            if completed < chat_count:
                await asyncio.sleep(BROADCAST_BATCH_DELAY_SECONDS)

        await edit_styled_text(
            m.message,
            s("broadcast_complete").format(
                total=chat_count,
                successful=successful,
                failed=failed,
            ),
            None,
        )
        if errors:
            file = io.BytesIO(errors.encode("utf-8"))
            file.name = "broadcast-errors.txt"
            await m.message.reply_document(file, caption=s("broadcast_errors_caption"))
    except Exception as e:
        await edit_styled_text(
            m.message,
            s("broadcast_failed").format(error=escape(str(e))),
            None,
        )


@Client.on_message(filters.command("chatstats", PREFIXES) & sudofilter)
@use_chat_lang
async def chat_statistics(c: Client, m: Message, s: Strings):
    """Get statistics about logged chats (sudoers only)"""
    try:
        stats = await get_chat_stats()
        all_chats = await get_all_chat_ids()

        stats_text = s("chatstats_title") + "\n\n"
        stats_text += s("chatstats_total").format(count=len(all_chats)) + "\n\n"
        stats_text += s("chatstats_breakdown") + "\n"

        total = 0
        for row in stats:
            chat_type, count = row
            stats_text += f"  • {chat_type}: {count}\n"
            total += count

        await m.reply_text(stats_text)
    except Exception as e:
        print(f"Error getting statistics: {e}")
        await m.reply_text(s("broadcast_failed").format(error=escape(str(e))))


commands.add_command("broadcast", "tools")
commands.add_command("chatstats", "tools")
