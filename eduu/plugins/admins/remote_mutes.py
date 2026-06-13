# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from __future__ import annotations

from hydrogram import Client, filters
from hydrogram.enums import ParseMode
from hydrogram.errors import BadRequest, RPCError
from hydrogram.types import Message

from config import PREFIXES
from eduu.utils import commands, extract_time, get_reason_text, sudofilter
from eduu.utils.consts import ADMIN_STATUSES
from eduu.utils.localization import Strings, use_chat_lang
from eduu.utils.moderation import apply_moderation_action
from .remote_utils import (
    _format_chat_title,
    _format_reason,
    _get_reason_text,
    _get_target_info,
    _reply_remote_action_failed,
)


@Client.on_message(filters.command("cmute", PREFIXES) & sudofilter)
@use_chat_lang
async def cmute(c: Client, m: Message, s: Strings):
    target_chat, target_user = await _get_target_info(c, m, s)
    if not target_chat or not target_user:
        return

    try:
        member = await target_chat.get_member(target_user.id)
    except BadRequest:
        member = None

    if member and member.status in ADMIN_STATUSES:
        await m.reply_text(s("mute_cannot_mute_admins"))
        return

    reason = get_reason_text(c, m)
    try:
        await apply_moderation_action(target_chat, target_user.id, "mute")
    except RPCError as e:
        await _reply_remote_action_failed(m, s, e)
        return

    text = s("cmute_success").format(
        user=target_user.mention,
        admin=m.from_user.mention,
        chat_title=_format_chat_title(target_chat),
    )
    await m.reply_text(text + _format_reason(reason, s))


@Client.on_message(filters.command("ctmute", PREFIXES) & sudofilter)
@use_chat_lang
async def ctmute(c: Client, m: Message, s: Strings):
    if len(m.command) < 4:
        await m.reply_text(
            s("remote_mod_time_usage").format(command=m.command[0]),
            parse_mode=ParseMode.DISABLED,
        )
        return

    target_chat, target_user = await _get_target_info(c, m, s)
    if not target_chat or not target_user:
        return

    try:
        member = await target_chat.get_member(target_user.id)
    except BadRequest:
        member = None

    if member and member.status in ADMIN_STATUSES:
        await m.reply_text(s("mute_cannot_mute_admins"))
        return

    mute_time = await extract_time(m, m.command[3])
    if not mute_time:
        return

    reason = _get_reason_text(m, 4)
    try:
        await apply_moderation_action(target_chat, target_user.id, "mute", until_date=mute_time)
    except RPCError as e:
        await _reply_remote_action_failed(m, s, e)
        return

    text = s("ctmute_success").format(
        user=target_user.mention,
        admin=m.from_user.mention,
        chat_title=_format_chat_title(target_chat),
        time=m.command[3],
    )
    await m.reply_text(text + _format_reason(reason, s))


@Client.on_message(filters.command("cunmute", PREFIXES) & sudofilter)
@use_chat_lang
async def cunmute(c: Client, m: Message, s: Strings):
    target_chat, target_user = await _get_target_info(c, m, s)
    if not target_chat or not target_user:
        return

    reason = get_reason_text(c, m)
    try:
        await apply_moderation_action(target_chat, target_user.id, "unmute")
    except RPCError as e:
        await _reply_remote_action_failed(m, s, e)
        return

    text = s("cunmute_success").format(
        user=target_user.mention,
        admin=m.from_user.mention,
        chat_title=_format_chat_title(target_chat),
    )
    await m.reply_text(text + _format_reason(reason, s))


commands.add_command("cmute", "remote_moderation")
commands.add_command("ctmute", "remote_moderation")
commands.add_command("cunmute", "remote_moderation")
