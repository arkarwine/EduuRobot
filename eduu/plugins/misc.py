# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

import re
from html import escape
from urllib.parse import quote, unquote

from hydrogram import Client, filters
from hydrogram.enums import ChatMembersFilter, ParseMode
from hydrogram.types import Message

from config import PREFIXES
from eduu.utils import commands
from eduu.utils.consts import ADMIN_STATUSES
from eduu.utils.localization import Strings, use_chat_lang

@Client.on_message(filters.command("admins", PREFIXES) & filters.group)
@use_chat_lang
async def mentionadmins(c: Client, m: Message, s: Strings):
    mention = ""
    async for i in m.chat.get_members(m.chat.id, filter=ChatMembersFilter.ADMINISTRATORS):
        if not (i.user.is_deleted or i.privileges.is_anonymous):
            mention += f"{i.user.mention}\n"
    await c.send_message(
        m.chat.id,
        s("admins_list").format(chat_title=m.chat.title, admins_list=mention),
    )


@Client.on_message(
    (filters.command(["report", "reportar"], PREFIXES) | filters.regex("^@admin"))
    & filters.group
    & filters.reply
)
@use_chat_lang
async def reportadmins(c: Client, m: Message, s: Strings):
    if not m.reply_to_message.from_user:
        return

    check_admin = await m.chat.get_member(m.reply_to_message.from_user.id)
    if check_admin.status in ADMIN_STATUSES:
        return

    mention = ""
    async for i in m.chat.get_members(filter=ChatMembersFilter.ADMINISTRATORS):
        if not (i.user.is_deleted or i.privileges.is_anonymous or i.user.is_bot):
            mention += f"<a href='tg://user?id={i.user.id}'>\u2063</a>"
    await m.reply_to_message.reply_text(
        s("report_admins").format(
            admins_list=mention,
            reported_user=m.reply_to_message.from_user.mention(),
        ),
    )

@Client.on_message(filters.command("parsebutton"))
@use_chat_lang
async def button_parse_helper(c: Client, m: Message, s: Strings):
    if len(m.text.split()) > 2:
        await m.reply_text(
            f"[{m.text.split(None, 2)[2]}](buttonurl:{m.command[1]})",
            parse_mode=ParseMode.DISABLED,
        )
    else:
        await m.reply_text(s("parsebtn_err"))


commands.add_command("admins", "general")
commands.add_command("parsebutton", "general")
