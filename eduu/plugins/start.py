# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from __future__ import annotations

import config

from hydrogram import Client, filters
from hydrogram.enums import ChatMembersFilter, ChatMemberStatus
from hydrogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    Message,
)

from config import OWNER_URL, PREFIXES, START_IMG_URL, UPDATES_CHANNEL
from eduu import __commit__, __copyright_year__, __version_number__
from eduu.utils import commands, linkify_commit
from eduu.utils.buttons import styled_button
from eduu.utils.localization import Strings, use_chat_lang
from eduu.utils.styled_messages import edit_styled_text, send_styled_photo, send_styled_text


# Using a low priority group so deeplinks will run before this and stop the propagation.
@Client.on_message(filters.command("start", PREFIXES) & filters.private, group=2)
@Client.on_callback_query(filters.regex("^start_back$"))
@use_chat_lang
async def start_pvt(c: Client, m: Message | CallbackQuery, s: Strings):
    msg = m.message if isinstance(m, CallbackQuery) else m

    buttons = [
        [
            styled_button(
                s("start_ai_btn"),
                callback_data="view_category ai",
                style="success",
            ),
        ],
        [
            styled_button(s("start_commands_btn"), callback_data="commands", style="primary"),
            styled_button(s("start_language_btn"), callback_data="chlang", style="primary"),
        ],
        [
            styled_button(
                s("start_add_to_chat_btn"),
                url=f"https://t.me/{c.me.username}?startgroup=new",
                style="success",
            ),
        ],
        [
            styled_button(s("start_updates_btn"), url=UPDATES_CHANNEL, style="primary"),
            styled_button(s("start_owner_btn"), url=OWNER_URL, style="primary"),
        ],
    ]

    if support_group := getattr(config, "SUPPORT_GROUP", ""):
        buttons[2].append(
            styled_button(s("start_support_group_btn"), url=support_group, style="primary")
        )

    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    start_text = s("start_private")

    if isinstance(m, CallbackQuery):
        await edit_styled_text(msg, start_text, keyboard)
        return

    if START_IMG_URL:
        try:
            await send_styled_photo(m, START_IMG_URL, start_text, keyboard)
            return
        except Exception:
            pass

    await send_styled_text(m, start_text, keyboard)


@Client.on_message(filters.command("start", PREFIXES) & filters.group, group=2)
@use_chat_lang
async def start_grp(c: Client, m: Message, s: Strings):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                styled_button(
                    s("start_chat"),
                    url=f"https://t.me/{c.me.username}?start=start",
                    style="success",
                )
            ]
        ]
    )
    await send_styled_text(m, s("start_group"), keyboard)


@Client.on_callback_query(filters.regex("^infos$"))
@use_chat_lang
async def infos(c: Client, m: CallbackQuery, s: Strings):
    res = s("start_info_page").format(
        version_number=f"r{__version_number__}",
        commit_hash=linkify_commit(__commit__),
        copyright_year=__copyright_year__,
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [styled_button(s("general_back_btn"), callback_data="start_back", style="danger")]
        ]
    )
    await edit_styled_text(
        m.message,
        res,
        keyboard,
        disable_web_page_preview=True,
    )


@Client.on_message(filters.command("owner", PREFIXES) & filters.group)
@use_chat_lang
async def get_group_owner(c: Client, m: Message, s: Strings):
    """Get the group owner"""
    async for member in m.chat.get_members(filter=ChatMembersFilter.ADMINISTRATORS):
        if member.status == ChatMemberStatus.OWNER:
            owner_info = s("owner_info").format(
                owner_name=member.user.first_name,
                owner_mention=member.user.mention(),
            )
            await m.reply_text(owner_info)
            return
    await m.reply_text(s("owner_not_found"))


commands.add_command("start", "general")
commands.add_command("owner", "general")
