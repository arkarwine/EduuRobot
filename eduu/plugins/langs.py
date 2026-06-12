# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from __future__ import annotations

from itertools import zip_longest

from hydrogram import Client, filters
from hydrogram.enums import ChatType
from hydrogram.types import (
    CallbackQuery,
    InlineKeyboardMarkup,
    Message,
)

from config import PREFIXES
from eduu.database.localization import set_db_lang
from eduu.utils.buttons import styled_button
from eduu.utils.decorators import require_admin
from eduu.utils.localization import Strings, langdict, use_chat_lang
from eduu.utils.styled_messages import edit_styled_text, send_styled_text


def gen_langs_kb():
    return [
        [
            styled_button(
                f"{langdict[lang]['_meta_language_flag']} {langdict[lang]['_meta_language_name']}",
                callback_data=f"set_lang {lang}",
            )
            for lang in langs
            if lang
        ]
        for langs in zip_longest(*[iter(langdict)] * 2)
    ]


@Client.on_callback_query(filters.regex("^chlang$"))
@Client.on_message(filters.command(["setchatlang", "setlang"], PREFIXES) & filters.group)
@require_admin(allow_in_private=True)
@use_chat_lang
async def chlang(c: Client, m: CallbackQuery | Message, s: Strings):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            *gen_langs_kb(),
            [styled_button(s("general_back_btn"), callback_data="start_back", style="danger")],
        ]
    )

    if isinstance(m, CallbackQuery):
        msg = m.message
    else:
        msg = m

    res = (
        s("language_changer_private")
        if msg.chat.type == ChatType.PRIVATE
        else s("language_changer_chat")
    )

    if isinstance(m, CallbackQuery):
        await edit_styled_text(msg, res, keyboard)
    else:
        await send_styled_text(msg, res, keyboard)


@Client.on_callback_query(filters.regex("^set_lang "))
@require_admin(allow_in_private=True)
async def set_chat_lang(c: Client, m: CallbackQuery):
    lang = m.data.split()[1]
    await set_db_lang(m.message.chat.id, m.message.chat.type, lang)

    await set_chat_lang_edit(c, m)


@use_chat_lang
async def set_chat_lang_edit(c: Client, m: CallbackQuery, s: Strings):
    if m.message.chat.type == ChatType.PRIVATE:
        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    styled_button(
                        s("general_back_btn"),
                        callback_data="start_back",
                        style="danger",
                    )
                ]
            ]
        )
    else:
        keyboard = None
    await edit_styled_text(m.message, s("language_changed_successfully"), keyboard)
