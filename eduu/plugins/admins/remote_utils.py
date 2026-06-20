# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from __future__ import annotations

from html import escape

from hydrogram.enums import ChatMemberStatus, ChatType, ParseMode
from hydrogram.errors import RPCError
from hydrogram.types import Chat, Message

from eduu.utils.localization import Strings


async def _resolve_chat(c, raw_chat: str):
    try:
        return await c.get_chat(raw_chat)
    except RPCError:
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


def _format_chat_title(chat: Chat) -> str:
    return escape(chat.title or chat.username or str(chat.id))


def _format_reason(reason: str | None, s: Strings) -> str:
    if not reason:
        return ""
    return "\n" + s("admins_reason_string").format(reason_text=escape(reason))


async def _reply_remote_action_failed(m: Message, s: Strings, error: RPCError) -> None:
    await m.reply_text(
        s("remote_mod_action_failed").format(
            error=f"{error.__class__.__name__}: {escape(str(error))}"
        )
    )


async def _get_target_info(c, m: Message, s: Strings):
    if len(m.command) < 3:
        await m.reply_text(
            s("remote_mod_usage").format(command=m.command[0]),
            parse_mode=ParseMode.DISABLED,
        )
        return None, None

    target_chat = await _resolve_chat(c, m.command[1])
    if not target_chat or target_chat.type == ChatType.PRIVATE:
        await m.reply_text(s("remote_mod_chat_not_found").format(chat=escape(m.command[1])))
        return None, None

    target_user_arg = m.command[2]
    try:
        target_user = await _resolve_user(c, target_user_arg)
    except Exception:
        await m.reply_text(s("remote_mod_user_not_found").format(user=escape(target_user_arg)))
        return None, None

    return target_chat, target_user


async def _get_target_chat(c, m: Message, s: Strings):
    if len(m.command) < 2:
        await m.reply_text(
            s("remote_mod_bulk_usage").format(command=m.command[0]),
            parse_mode=ParseMode.DISABLED,
        )
        return None

    target_chat = await _resolve_chat(c, m.command[1])
    if not target_chat or target_chat.type == ChatType.PRIVATE:
        await m.reply_text(s("remote_mod_chat_not_found").format(chat=escape(m.command[1])))
        return None

    return target_chat


async def _get_non_admin_users(chat: Chat):
    users = []
    skipped = 0
    async for member in chat.get_members():
        if member.status in {ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR}:
            skipped += 1
            continue
        if not member.user or member.user.is_bot:
            skipped += 1
            continue
        users.append(member.user)
    return users, skipped


async def _verify_remote_action(chat: Chat, user_id: int, action: str) -> bool:
    try:
        member = await chat.get_member(user_id)
    except RPCError:
        return action in {"ban", "kick"}

    if action in {"ban", "kick"}:
        return member.status in {ChatMemberStatus.BANNED, ChatMemberStatus.LEFT}
    if action == "mute":
        privileges = getattr(member, "privileges", None)
        permissions = getattr(member, "permissions", None)
        if member.status == ChatMemberStatus.RESTRICTED:
            return not getattr(permissions, "can_send_messages", True)
        return privileges is None and not getattr(permissions, "can_send_messages", True)
    if action in {"unban", "unmute"}:
        return member.status not in {ChatMemberStatus.BANNED, ChatMemberStatus.RESTRICTED}
    return True


async def _reply_remote_state_failed(m: Message, s: Strings, action: str, chat: Chat) -> None:
    await m.reply_text(
        s("remote_mod_state_failed").format(
            action=action,
            chat_title=_format_chat_title(chat),
        )
    )


async def _reply_remote_bulk_result(
    m: Message,
    s: Strings,
    *,
    action: str,
    chat: Chat,
    success: int,
    failed: int,
    skipped: int,
    reason: str | None = None,
) -> None:
    text = s("remote_mod_bulk_result").format(
        action=action,
        chat_title=_format_chat_title(chat),
        success=success,
        failed=failed,
        skipped=skipped,
    )
    await m.reply_text(text + _format_reason(reason, s))
