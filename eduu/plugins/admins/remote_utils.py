# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from __future__ import annotations

from hydrogram.errors import BadRequest
from hydrogram.enums import ChatType
from hydrogram.types import Message

from eduu.utils.localization import Strings


async def _resolve_chat(c, raw_chat: str):
    try:
        return await c.get_chat(raw_chat)
    except BadRequest:
        return None


async def _resolve_user(c, raw_user: str):
    if raw_user.isdecimal():
        return await c.get_users(int(raw_user))
    return await c.get_users(raw_user)


def _get_reason_text(m: Message, start_index: int = 3) -> str | None:
    parts = m.text.split(None, start_index)
    if len(parts) > start_index:
        return parts[-1]
    return None


async def _get_target_info(c, m: Message, s: Strings):
    if len(m.command) < 3:
        await m.reply_text(s("remote_mod_usage").format(command=m.command[0]))
        return None, None

    target_chat = await _resolve_chat(c, m.command[1])
    if not target_chat or target_chat.type == ChatType.PRIVATE:
        await m.reply_text(s("remote_mod_chat_not_found").format(chat=m.command[1]))
        return None, None

    target_user_arg = m.command[2]
    try:
        target_user = await _resolve_user(c, target_user_arg)
    except Exception:
        await m.reply_text(s("remote_mod_user_not_found").format(user=target_user_arg))
        return None, None

    return target_chat, target_user
