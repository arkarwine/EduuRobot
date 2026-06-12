# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from itertools import zip_longest

from hydrogram import Client, filters
from hydrogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    Message,
)

from eduu.utils import commands
from eduu.utils.buttons import styled_button
from eduu.utils.decorators import stop_here
from eduu.utils.localization import Strings, use_chat_lang
from eduu.utils.styled_messages import edit_styled_text, send_styled_text


def gen_categories_kb(strings_manager):
    return [
        [
            styled_button(
                strings_manager(f"cmds_category_{category}"),
                callback_data=f"view_category {category}",
                style="primary",
            )
            for category in categories
            if category
        ]
        for categories in zip_longest(*[iter(commands.commands)] * 2)
    ]


@Client.on_callback_query(filters.regex("^commands$"))
@use_chat_lang
async def cmds_list(c: Client, m: CallbackQuery, s: Strings):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            *gen_categories_kb(s),
            [styled_button(s("general_back_btn"), callback_data="start_back", style="danger")],
        ]
    )
    await edit_styled_text(m.message, s("cmds_list_select_category"), keyboard)


@Client.on_message(filters.command(["help", "start help"]) & filters.private)
@use_chat_lang
@stop_here
async def show_private_help(c: Client, m: Message, s: Strings):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            *gen_categories_kb(s),
            [
                styled_button(
                    s("general_back_btn"),
                    callback_data="start_back",
                    style="danger",
                )
            ],
        ]
    )
    await send_styled_text(m, s("cmds_list_select_category"), keyboard)


@Client.on_message(filters.command(["help", "start help"]))
@use_chat_lang
@stop_here
async def show_help(c: Client, m: Message, s: Strings):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                styled_button(
                    s("start_chat"),
                    url=f"https://t.me/{c.me.username}?start=help",
                    style="success",
                )
            ]
        ]
    )
    await send_styled_text(m, s("cmds_list_group_help"), keyboard)


@Client.on_callback_query(filters.regex("^view_category .+"))
@use_chat_lang
async def get_category(c: Client, m: CallbackQuery, s: Strings):
    msg = commands.get_commands_message(s, m.data.split(maxsplit=1)[1])
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [styled_button(s("general_back_btn"), callback_data="commands", style="danger")]
        ]
    )
    await edit_styled_text(m.message, msg, keyboard)
