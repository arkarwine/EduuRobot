# SPDX-License-Identifier: MIT

from __future__ import annotations

from datetime import datetime

from hydrogram.types import Chat, ChatPermissions

from eduu.database.warns import add_warns, get_warn_action, get_warns, get_warns_limit, reset_warns


async def apply_moderation_action(
    chat: Chat,
    user_id: int,
    action: str,
    *,
    until_date: datetime | None = None,
) -> None:
    if action == "ban":
        await chat.ban_member(user_id, until_date=until_date)
    elif action == "mute":
        await chat.restrict_member(
            user_id,
            ChatPermissions(can_send_messages=False),
            until_date=until_date,
        )
    elif action == "kick":
        await chat.ban_member(user_id)
        await chat.unban_member(user_id)
    elif action in {"unban", "unmute"}:
        await chat.unban_member(user_id)
    else:
        raise ValueError(f"Unsupported moderation action: {action}")


async def get_missing_bot_permissions(chat: Chat, *permissions: str) -> list[str]:
    member = await chat.get_member("me")
    privileges = member.privileges
    return [
        permission
        for permission in permissions
        if not privileges or not getattr(privileges, permission, False)
    ]


async def add_warning_and_apply_action(chat: Chat, user_id: int) -> tuple[int, int, str | None]:
    await add_warns(chat.id, user_id, 1)
    count = await get_warns(chat.id, user_id)
    limit = await get_warns_limit(chat.id)
    if count < limit:
        return count, limit, None

    action = await get_warn_action(chat.id)
    await apply_moderation_action(chat, user_id, action)
    await reset_warns(chat.id, user_id)
    return count, limit, action
