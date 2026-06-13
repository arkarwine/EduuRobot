# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from hydrogram import Client, filters
from hydrogram.types import ChatPrivileges, Message

from config import PREFIXES
from eduu.utils import commands, extract_time, get_reason_text, get_target_user
from eduu.utils.consts import ADMIN_STATUSES
from eduu.utils.decorators import require_admin
from eduu.utils.localization import Strings, use_chat_lang
from eduu.utils.moderation import apply_moderation_action


@Client.on_message(filters.command("ban", PREFIXES))
@use_chat_lang
@require_admin(ChatPrivileges(can_restrict_members=True))
async def ban(c: Client, m: Message, s: Strings):
    target_user = await get_target_user(c, m)
    if not target_user:
        await m.reply_text(s("moderation_target_required"))
        return
    reason = get_reason_text(c, m)
    check_admin = await m.chat.get_member(target_user.id)
    if check_admin.status in ADMIN_STATUSES:
        await m.reply_text(s("ban_cannot_ban_admins"))
        return

    try:
        await apply_moderation_action(m.chat, target_user.id, "ban")
    except Exception as error:
        await m.reply_text(s("moderation_action_failed").format(error=error))
        return
    text = s("ban_success").format(
        user=target_user.mention,
        admin=m.from_user.mention,
    )
    if reason:
        await m.reply_text(text + "\n" + s("admins_reason_string").format(reason_text=reason))
    else:
        await m.reply_text(text)


@Client.on_message(filters.command("kick", PREFIXES))
@use_chat_lang
@require_admin(ChatPrivileges(can_restrict_members=True))
async def kick(c: Client, m: Message, s: Strings):
    target_user = await get_target_user(c, m)
    if not target_user:
        await m.reply_text(s("moderation_target_required"))
        return
    reason = get_reason_text(c, m)
    check_admin = await m.chat.get_member(target_user.id)
    if check_admin.status in ADMIN_STATUSES:
        await m.reply_text(s("kick_cannot_kick_admins"))
        return

    try:
        await apply_moderation_action(m.chat, target_user.id, "kick")
    except Exception as error:
        await m.reply_text(s("moderation_action_failed").format(error=error))
        return
    text = s("kick_success").format(
        user=target_user.mention,
        admin=m.from_user.mention,
    )
    if reason:
        await m.reply_text(text + "\n" + s("admins_reason_string").format(reason_text=reason))
    else:
        await m.reply_text(text)


@Client.on_message(filters.command("unban", PREFIXES))
@use_chat_lang
@require_admin(ChatPrivileges(can_restrict_members=True))
async def unban(c: Client, m: Message, s: Strings):
    target_user = await get_target_user(c, m)
    if not target_user:
        await m.reply_text(s("moderation_target_required"))
        return
    reason = get_reason_text(c, m)
    try:
        await apply_moderation_action(m.chat, target_user.id, "unban")
    except Exception as error:
        await m.reply_text(s("moderation_action_failed").format(error=error))
        return
    text = s("unban_success").format(
        user=target_user.mention,
        admin=m.from_user.mention,
    )
    if reason:
        await m.reply_text(text + "\n" + s("admins_reason_string").format(reason_text=reason))
    else:
        await m.reply_text(text)


@Client.on_message(filters.command("tban", PREFIXES))
@use_chat_lang
@require_admin(ChatPrivileges(can_restrict_members=True))
async def tban(c: Client, m: Message, s: Strings):
    if not m.reply_to_message or not m.reply_to_message.from_user:
        await m.reply_text(s("moderation_reply_target_required"))
        return
    if len(m.command) == 1:
        await m.reply_text(s("admins_error_must_specify_time").format(command=m.command[0]))
        return

    split_time = m.text.split(None, 1)
    ban_time = await extract_time(m, split_time[1])
    if not ban_time:
        return
    try:
        await apply_moderation_action(
            m.chat,
            m.reply_to_message.from_user.id,
            "ban",
            until_date=ban_time,
        )
    except Exception as error:
        await m.reply_text(s("moderation_action_failed").format(error=error))
        return

    await m.reply_text(
        s("tban_success").format(
            user=m.reply_to_message.from_user.mention,
            admin=m.from_user.mention,
            time=split_time[1],
        )
    )


commands.add_command("ban", "admin_bans")
commands.add_command("kick", "admin_bans")
commands.add_command("tban", "admin_bans")
commands.add_command("unban", "admin_bans")
