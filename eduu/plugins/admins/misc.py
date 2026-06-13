# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from hydrogram import Client, filters
from hydrogram.types import CallbackQuery, ChatPrivileges, InlineKeyboardMarkup, Message

from config import PREFIXES
from eduu.database.admins import check_if_del_service, toggle_del_service
from eduu.utils import commands
from eduu.utils.buttons import styled_button
from eduu.utils.decorators import require_admin
from eduu.utils.localization import Strings, use_chat_lang
from eduu.utils.styled_messages import edit_styled_text, send_styled_text


@Client.on_message(filters.command("purge", PREFIXES))
@require_admin(ChatPrivileges(can_delete_messages=True), allow_in_private=True)
@use_chat_lang
async def purge(c: Client, m: Message, s: Strings):
    """Purge upto the replied message."""
    if not m.reply_to_message:
        await m.reply_text(s("purge_reply_required"))
        return
    keyboard = InlineKeyboardMarkup(
        [[
            styled_button(
                s("confirm_action_btn"),
                callback_data=f"confirm_purge {m.from_user.id} {m.reply_to_message.id} {m.id}",
                style="danger",
            ),
            styled_button(s("cancel_action_btn"), callback_data="cancel_destructive"),
        ]]
    )
    await send_styled_text(m, s("purge_confirm"), keyboard)


@Client.on_callback_query(filters.regex(r"^confirm_purge "))
@require_admin(ChatPrivileges(can_delete_messages=True), allow_in_private=True)
@use_chat_lang
async def confirm_purge(c: Client, m: CallbackQuery, s: Strings):
    _, owner_id, start_id, end_id = m.data.split()
    if m.from_user.id != int(owner_id):
        await m.answer(s("confirmation_wrong_admin"), show_alert=True)
        return
    await edit_styled_text(m.message, s("purge_in_progress"), None)
    message_ids = list(range(int(start_id), int(end_id) + 1))
    deleted = 0
    for index in range(0, len(message_ids), 100):
        batch = message_ids[index : index + 100]
        await c.delete_messages(m.message.chat.id, batch)
        deleted += len(batch)
    await edit_styled_text(m.message, s("purge_success").format(count=deleted), None)


@Client.on_callback_query(filters.regex(r"^cancel_destructive$"))
@require_admin(allow_in_private=True)
@use_chat_lang
async def cancel_destructive(c: Client, m: CallbackQuery, s: Strings):
    await edit_styled_text(m.message, s("action_cancelled"), None)
@Client.on_message(filters.command("cleanservice", PREFIXES))
@require_admin(ChatPrivileges(can_delete_messages=True))
@use_chat_lang
async def delservice(c: Client, m: Message, s: Strings):
    if len(m.text.split()) > 1:
        if m.command[1] == "on":
            await toggle_del_service(m.chat.id, True)
            await m.reply_text(s("cleanservice_enabled"))
        elif m.command[1] == "off":
            await toggle_del_service(m.chat.id, None)
            await m.reply_text(s("cleanservice_disabled"))
        else:
            await m.reply_text(s("cleanservice_invalid_arg"))
    else:
        check_delservice = await check_if_del_service(m.chat.id)
        if check_delservice is None:
            await m.reply_text(s("cleanservice_status_disabled"))
        else:
            await m.reply_text(s("cleanservice_status_enabled"))


@Client.on_message(filters.service, group=-1)
async def delservice_action(c: Client, m: Message):
    get_delservice = await check_if_del_service(m.chat.id)
    if not get_delservice:
        return

    self_member = await m.chat.get_member("me")

    if self_member.privileges and self_member.privileges.can_delete_messages:
        await m.delete()


commands.add_command("cleanservice", "admin_misc")
commands.add_command("purge", "admin_misc")
