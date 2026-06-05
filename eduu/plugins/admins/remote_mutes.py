# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from __future__ import annotations

from hydrogram import Client, filters
from hydrogram.enums import ChatType
from hydrogram.errors import BadRequest
from hydrogram.types import Message, ChatPermissions

from config import PREFIXES
from eduu.utils import commands, get_reason_text, sudofilter
from eduu.utils.consts import ADMIN_STATUSES
from eduu.utils.localization import Strings, use_chat_lang
from .remote_utils import _resolve_chat, _resolve_user, _get_target_info, _get_reason_text
from eduu.utils import extract_time



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
    await target_chat.restrict_member(target_user.id, ChatPermissions(can_send_messages=False))

    text = s("cmute_success").format(
        user=target_user.mention,
        admin=m.from_user.mention,
        chat_title=target_chat.title or target_chat.username or str(target_chat.id),
    )
    if reason:
        await m.reply_text(text + "\n" + s("admins_reason_string").format(reason_text=reason))
    else:
        await m.reply_text(text)


@Client.on_message(filters.command("ctmute", PREFIXES) & sudofilter)
@use_chat_lang
async def ctmute(c: Client, m: Message, s: Strings):
    if len(m.command) < 4:
        await m.reply_text(s("remote_mod_time_usage").format(command=m.command[0]))
        return

    target_chat = await _resolve_chat(c, m.command[1])
    if not target_chat or target_chat.type == ChatType.PRIVATE:
        await m.reply_text(s("remote_mod_chat_not_found").format(chat=m.command[1]))
        return

    try:
        target_user = await _resolve_user(c, m.command[2])
    except Exception:
        await m.reply_text(s("remote_mod_user_not_found").format(user=m.command[2]))
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
    await target_chat.restrict_member(
        target_user.id,
        ChatPermissions(can_send_messages=False),
        until_date=mute_time,
    )

    text = s("ctmute_success").format(
        user=target_user.mention,
        admin=m.from_user.mention,
        chat_title=target_chat.title or target_chat.username or str(target_chat.id),
        time=m.command[3],
    )
    if reason:
        await m.reply_text(text + "\n" + s("admins_reason_string").format(reason_text=reason))
    else:
        await m.reply_text(text)


@Client.on_message(filters.command("cunmute", PREFIXES) & sudofilter)
@use_chat_lang
async def cunmute(c: Client, m: Message, s: Strings):
    target_chat, target_user = await _get_target_info(c, m, s)
    if not target_chat or not target_user:
        return

    reason = get_reason_text(c, m)
    await target_chat.unban_member(target_user.id)

    text = s("cunmute_success").format(
        user=target_user.mention,
        admin=m.from_user.mention,
        chat_title=target_chat.title or target_chat.username or str(target_chat.id),
    )
    if reason:
        await m.reply_text(text + "\n" + s("admins_reason_string").format(reason_text=reason))
    else:
        await m.reply_text(text)


commands.add_command("cmute", "remote_moderation")
commands.add_command("ctmute", "remote_moderation")
commands.add_command("cunmute", "remote_moderation")
