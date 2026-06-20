# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from __future__ import annotations

from hydrogram import Client, filters
from hydrogram.enums import ParseMode
from hydrogram.errors import BadRequest, RPCError
from hydrogram.types import Message

from config import PREFIXES
from eduu.utils import commands, extract_time, sudofilter
from eduu.utils.consts import ADMIN_STATUSES
from eduu.utils.localization import Strings, use_chat_lang
from eduu.utils.moderation import apply_moderation_action
from .remote_utils import (
    _format_chat_title,
    _format_reason,
    _get_reason_text,
    _get_non_admin_users,
    _get_target_chat,
    _get_target_info,
    _reply_remote_bulk_result,
    _reply_remote_action_failed,
    _reply_remote_state_failed,
    _verify_remote_action,
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

    reason = _get_reason_text(m)
    try:
        await apply_moderation_action(target_chat, target_user.id, "mute")
    except RPCError as e:
        await _reply_remote_action_failed(m, s, e)
        return

    if not await _verify_remote_action(target_chat, target_user.id, "mute"):
        await _reply_remote_state_failed(m, s, "mute", target_chat)
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

    if not await _verify_remote_action(target_chat, target_user.id, "mute"):
        await _reply_remote_state_failed(m, s, "mute", target_chat)
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

    reason = _get_reason_text(m)
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


async def _run_bulk_mute_action(c: Client, m: Message, s: Strings, *, until_date=None):
    target_chat = await _get_target_chat(c, m, s)
    if not target_chat:
        return

    reason = _get_reason_text(m, 3 if until_date else 2)
    try:
        users, skipped = await _get_non_admin_users(target_chat)
    except RPCError as e:
        await _reply_remote_action_failed(m, s, e)
        return

    success = 0
    failed = 0
    for user in users:
        try:
            await apply_moderation_action(
                target_chat,
                user.id,
                "mute",
                until_date=until_date,
            )
            if await _verify_remote_action(target_chat, user.id, "mute"):
                success += 1
            else:
                failed += 1
        except RPCError:
            failed += 1

    await _reply_remote_bulk_result(
        m,
        s,
        action="mute",
        chat=target_chat,
        success=success,
        failed=failed,
        skipped=skipped,
        reason=reason,
    )


@Client.on_message(filters.command(["cmuteall", "cmute_all"], PREFIXES) & sudofilter)
@use_chat_lang
async def cmuteall(c: Client, m: Message, s: Strings):
    await _run_bulk_mute_action(c, m, s)


@Client.on_message(filters.command(["ctmuteall", "ctmute_all"], PREFIXES) & sudofilter)
@use_chat_lang
async def ctmuteall(c: Client, m: Message, s: Strings):
    if len(m.command) < 3:
        await m.reply_text(
            s("remote_mod_bulk_time_usage").format(command=m.command[0]),
            parse_mode=ParseMode.DISABLED,
        )
        return

    mute_time = await extract_time(m, m.command[2])
    if not mute_time:
        return

    await _run_bulk_mute_action(c, m, s, until_date=mute_time)


commands.add_command("cmute", "remote_moderation")
commands.add_command("cmuteall", "remote_moderation", aliases=["cmute_all"])
commands.add_command("ctmute", "remote_moderation")
commands.add_command("ctmuteall", "remote_moderation", aliases=["ctmute_all"])
commands.add_command("cunmute", "remote_moderation")
