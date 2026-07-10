# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

import asyncio
import logging
from html import escape
from time import time

from hydrogram import Client, filters
from hydrogram.enums import ParseMode
from hydrogram.errors import BadRequest, RPCError
from hydrogram.types import ChatMemberUpdated, ChatPrivileges, InlineKeyboardMarkup, Message

from config import PREFIXES
from eduu.database.welcome import (
    get_default_template,
    get_greeting_delete_seconds,
    get_goodbye,
    get_welcome,
    reset_default_template,
    set_default_template,
    set_greeting_delete_seconds,
    set_goodbye,
    set_welcome,
    toggle_goodbye,
    toggle_welcome,
)
from eduu.utils import button_parser, commands, get_format_keys, sudofilter
from eduu.utils.custom_emoji import render_custom_emoji_text
from eduu.utils.decorators import require_admin, stop_here
from eduu.utils.localization import Strings, use_chat_lang

logger = logging.getLogger(__name__)

NON_MEMBER_STATUSES = {"left", "banned", "restricted", "kicked"}
MEMBER_STATUSES = {"member", "administrator", "owner"}
DEFAULT_GREETING_DELETE_SECONDS = 10
PROFILE_PHOTO_TOKENS = {"{profile_photo}", "{user_photo}"}
_recent_member_updates: dict[tuple[int, int, str], float] = {}


@Client.on_message(
    filters.command(
        ["welcomeformat", "goodbyeformat", "start welcome_format_help"],
        PREFIXES,
    )
)
@use_chat_lang
@stop_here
async def welcome_format_message_help(c: Client, m: Message, s: Strings):
    await m.reply_text(s("welcome_format_help_msg"))


def _message_media(src: Message) -> tuple[str | None, str | None, str | None]:
    if src.photo:
        return _rich_text(src, caption=True), src.photo.file_id, "photo"
    if src.video:
        return _rich_text(src, caption=True), src.video.file_id, "video"
    return _rich_text(src) or _rich_text(src, caption=True), None, None


def _rich_text(m: Message, *, caption: bool = False) -> str | None:
    text = m.caption if caption else m.text
    if text is None:
        return None
    return getattr(text, "html", None) or str(text)


async def _preview_template(c: Client, m: Message, text: str | None, s: Strings) -> Message:
    if not text:
        return await m.reply_text(s("welcome_set_success"))
    preview = text.replace("{profile_photo}", "").replace("{user_photo}", "").format(
        id=m.from_user.id,
        username=escape(m.from_user.username or ""),
        mention=m.from_user.mention,
        first_name=escape(m.from_user.first_name or ""),
        full_name=escape(m.from_user.full_name or ""),
        name=escape(m.from_user.first_name or ""),
        title=escape(m.chat.title or ""),
        chat_title=escape(m.chat.title or ""),
        count=(await c.get_chat_members_count(m.chat.id)),
    )
    return await m.reply_text(preview)


async def _delete_after(message: Message | None, delay: int) -> None:
    if not message or delay <= 0:
        return
    await asyncio.sleep(delay)
    try:
        await message.delete()
    except RPCError:
        pass


async def _set_template_message(
    c: Client,
    m: Message,
    s: Strings,
    *,
    kind: str,
) -> None:
    if not m.reply_to_message:
        empty_key = "welcome_set_empty" if kind == "welcome" else "goodbye_set_empty"
        await m.reply_text(
            s(empty_key).format(bot_username=c.me.username),
            disable_web_page_preview=True,
        )
        return

    message, media_file_id, media_type = _message_media(m.reply_to_message)
    if not message and not media_file_id:
        empty_key = "welcome_set_empty" if kind == "welcome" else "goodbye_set_empty"
        await m.reply_text(s(empty_key).format(bot_username=c.me.username))
        return

    try:
        sent = await _preview_template(c, m, message, s)
    except (KeyError, BadRequest) as e:
        error_key = "welcome_set_error" if kind == "welcome" else "goodbye_set_error"
        await m.reply_text(s(error_key).format(error=f"{e.__class__.__name__}: {e!s}"))
        return

    if kind == "welcome":
        await set_welcome(m.chat.id, message, media_file_id, media_type)
        success_key = "welcome_set_success"
    else:
        await set_goodbye(m.chat.id, message, media_file_id, media_type)
        success_key = "goodbye_set_success"
    await sent.edit_text(s(success_key).format(chat_title=escape(m.chat.title or "")))


def _command_text(m: Message) -> str:
    text = _rich_text(m)
    if not text:
        return ""
    parts = text.split(None, 1)
    return parts[1].strip() if len(parts) > 1 else ""


def _template_from_command_or_reply(m: Message) -> str | None:
    text = _command_text(m)
    if text:
        return text
    if not m.reply_to_message:
        return None
    return _rich_text(m.reply_to_message) or _rich_text(m.reply_to_message, caption=True)


async def _preview_default_template(m: Message, text: str) -> Message:
    preview = text.replace("{profile_photo}", "").replace("{user_photo}", "").format(
        id=m.from_user.id,
        username=escape(m.from_user.username or ""),
        mention=m.from_user.mention,
        first_name=escape(m.from_user.first_name or ""),
        full_name=escape(m.from_user.full_name or ""),
        name=escape(m.from_user.first_name or ""),
        title=escape(m.chat.title or "Test Chat"),
        chat_title=escape(m.chat.title or "Test Chat"),
        count=1,
    )
    return await m.reply_text(preview)


def _profile_photo_file_id(user) -> str | None:
    photo = getattr(user, "photo", None)
    for attr in ("big_file_id", "small_file_id"):
        file_id = getattr(photo, attr, None)
        if file_id:
            return file_id
    return None


async def _download_profile_photo(c: Client, file_id: str):
    try:
        return await c.download_media(file_id, in_memory=True)
    except Exception as e:
        logger.debug("Could not download profile photo: %s", e)
        return None


async def _profile_photo_media(c: Client, user):
    file_id = _profile_photo_file_id(user)
    if file_id:
        media = await _download_profile_photo(c, file_id)
        if media:
            return media

    try:
        fresh_user = await c.get_users(user.id)
    except Exception as e:
        logger.debug("Could not refresh user %s for profile photo: %s", user.id, e)
    else:
        file_id = _profile_photo_file_id(fresh_user)
        if file_id:
            media = await _download_profile_photo(c, file_id)
            if media:
                return media

    try:
        async for photo in c.get_chat_photos(user.id, limit=1):
            media = await _download_profile_photo(c, photo.file_id)
            if media:
                return media
    except Exception as e:
        logger.debug("Could not fetch chat photos for user %s: %s", user.id, e)

    return None


async def _set_default_template_message(
    c: Client,
    m: Message,
    s: Strings,
    *,
    kind: str,
) -> None:
    _ = c
    text = _template_from_command_or_reply(m)
    if not text:
        await m.reply_text(s(f"{kind}_default_set_empty"))
        return
    try:
        sent = await _preview_default_template(m, text)
    except (KeyError, BadRequest) as e:
        await m.reply_text(s(f"{kind}_set_error").format(error=f"{e.__class__.__name__}: {e!s}"))
        return
    await set_default_template(kind, text)
    await sent.edit_text(s(f"{kind}_default_set_success"))


@Client.on_message(filters.command("setwelcome", PREFIXES) & filters.group)
@require_admin(ChatPrivileges(can_change_info=True))
@use_chat_lang
async def set_welcome_message(c: Client, m: Message, s: Strings):
    await _set_template_message(c, m, s, kind="welcome")


@Client.on_message(filters.command("setgoodbye", PREFIXES) & filters.group)
@require_admin(ChatPrivileges(can_change_info=True))
@use_chat_lang
async def set_goodbye_message(c: Client, m: Message, s: Strings):
    await _set_template_message(c, m, s, kind="goodbye")


@Client.on_message(filters.command("setdefaultwelcome", PREFIXES) & sudofilter)
@use_chat_lang
async def set_default_welcome_message(c: Client, m: Message, s: Strings):
    await _set_default_template_message(c, m, s, kind="welcome")


@Client.on_message(filters.command("setdefaultgoodbye", PREFIXES) & sudofilter)
@use_chat_lang
async def set_default_goodbye_message(c: Client, m: Message, s: Strings):
    await _set_default_template_message(c, m, s, kind="goodbye")


def _recently_processed(chat_id: int, user_id: int, kind: str) -> bool:
    key = (chat_id, user_id, kind)
    now = time()
    if key in _recent_member_updates and now - _recent_member_updates[key] < 5:
        return True
    _recent_member_updates[key] = now
    return False


async def _send_template(
    c: Client,
    chat_id: int,
    chat_title: str,
    members: list,
    s: Strings,
    *,
    kind: str,
) -> None:
    if kind == "welcome":
        template, enabled, media_file_id, media_type = await get_welcome(chat_id)
        default_text = await get_default_template("welcome", s("welcome_default"))
    else:
        template, enabled, media_file_id, media_type = await get_goodbye(chat_id)
        default_text = await get_default_template("goodbye", s("goodbye_default"))

    if not enabled:
        return

    template = template or default_text
    use_profile_photo = any(token in template for token in PROFILE_PHOTO_TOKENS)
    template = template.replace("{profile_photo}", "").replace("{user_photo}", "")
    count = (
        await c.get_chat_members_count(chat_id)
        if "count" in get_format_keys(template)
        else 0
    )
    mention = ", ".join(user.mention for user in members)
    username = ", ".join(
        f"@{escape(user.username)}" if user.username else user.mention for user in members
    )
    user_id = ", ".join(str(user.id) for user in members)
    full_name = ", ".join(escape(user.full_name or "") for user in members)
    first_name = ", ".join(escape(user.first_name or "") for user in members)

    text = template.format(
        id=user_id,
        username=username,
        mention=mention,
        first_name=first_name,
        full_name=full_name,
        name=full_name,
        title=escape(chat_title or ""),
        chat_title=escape(chat_title or ""),
        count=count,
    )
    text = render_custom_emoji_text(text)
    text, buttons = button_parser(text)
    if not text.strip():
        text = mention
    reply_markup = InlineKeyboardMarkup(buttons) if buttons else None

    sent = None
    try:
        profile_photo = (
            await _profile_photo_media(c, members[0])
            if use_profile_photo and len(members) == 1
            else None
        )
        if profile_photo:
            try:
                sent = await c.send_photo(
                    chat_id=chat_id,
                    photo=profile_photo,
                    caption=text,
                    reply_markup=reply_markup,
                    parse_mode=ParseMode.HTML,
                )
            finally:
                close = getattr(profile_photo, "close", None)
                if close:
                    close()
        elif media_file_id and media_type == "photo":
            sent = await c.send_photo(
                chat_id=chat_id,
                photo=media_file_id,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
        elif media_file_id and media_type == "video":
            sent = await c.send_video(
                chat_id=chat_id,
                video=media_file_id,
                caption=text,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
    except Exception:
        sent = None

    if sent is None:
        sent = await c.send_message(
            chat_id=chat_id,
            text=text,
            disable_web_page_preview=True,
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML,
        )

    delete_seconds = await get_greeting_delete_seconds(chat_id)
    asyncio.create_task(_delete_after(sent, delete_seconds))


@Client.on_chat_member_updated()
@use_chat_lang
async def handle_member_update(c: Client, update: ChatMemberUpdated, s: Strings):
    old_status = update.old_chat_member.status.value if update.old_chat_member else "left"
    new_status = update.new_chat_member.status.value if update.new_chat_member else "left"

    if old_status in NON_MEMBER_STATUSES and new_status in MEMBER_STATUSES:
        user = update.new_chat_member.user
        kind = "welcome"
    elif old_status in MEMBER_STATUSES and new_status in NON_MEMBER_STATUSES:
        user = update.old_chat_member.user
        kind = "goodbye"
    else:
        return

    if user.is_bot or _recently_processed(update.chat.id, user.id, kind):
        return

    logger.info("Processing %s for %s in %s", kind, user.id, update.chat.id)
    await _send_template(c, update.chat.id, update.chat.title, [user], s, kind=kind)


@Client.on_message(filters.new_chat_members & filters.group)
@use_chat_lang
async def greet_new_members_message(c: Client, m: Message, s: Strings):
    members = [user for user in m.new_chat_members if not user.is_bot]
    members = [
        user for user in members if not _recently_processed(m.chat.id, user.id, "welcome")
    ]
    if not members:
        return

    logger.info(
        "Processing welcome (new_chat_members) for %s in %s",
        [u.id for u in members],
        m.chat.id,
    )
    await _send_template(c, m.chat.id, m.chat.title, members, s, kind="welcome")


@Client.on_message(
    (filters.command("welcome") & ~filters.command(["welcome on", "welcome off"])) & filters.group
)
@require_admin(ChatPrivileges(can_change_info=True))
@use_chat_lang
async def invalid_welcome_status_arg(c: Client, m: Message, s: Strings):
    await m.reply_text(s("welcome_mode_invalid"))


@Client.on_message(
    (filters.command("goodbye") & ~filters.command(["goodbye on", "goodbye off"])) & filters.group
)
@require_admin(ChatPrivileges(can_change_info=True))
@use_chat_lang
async def invalid_goodbye_status_arg(c: Client, m: Message, s: Strings):
    await m.reply_text(s("goodbye_mode_invalid"))


@Client.on_message(filters.command("getwelcome", PREFIXES) & filters.group)
@require_admin(ChatPrivileges(can_change_info=True))
@use_chat_lang
async def getwelcomemsg(c: Client, m: Message, s: Strings):
    welcome, welcome_enabled, media_file_id, media_type = await get_welcome(m.chat.id)
    if welcome_enabled:
        text = (
            await get_default_template("welcome", s("welcome_default"))
            if welcome is None
            else welcome
        )
        msg = f"{text}\n\n" + (f"[Media: {media_type}]" if media_file_id else "")
        await m.reply_text(msg, parse_mode=ParseMode.DISABLED)
    else:
        await m.reply_text("None")


@Client.on_message(filters.command("getgoodbye", PREFIXES) & filters.group)
@require_admin(ChatPrivileges(can_change_info=True))
@use_chat_lang
async def getgoodbyemsg(c: Client, m: Message, s: Strings):
    goodbye, goodbye_enabled, media_file_id, media_type = await get_goodbye(m.chat.id)
    if goodbye_enabled:
        text = (
            await get_default_template("goodbye", s("goodbye_default"))
            if goodbye is None
            else goodbye
        )
        msg = f"{text}\n\n" + (f"[Media: {media_type}]" if media_file_id else "")
        await m.reply_text(msg, parse_mode=ParseMode.DISABLED)
    else:
        await m.reply_text("None")


@Client.on_message(filters.command("getdefaultwelcome", PREFIXES) & sudofilter)
@use_chat_lang
async def get_default_welcome_message(c: Client, m: Message, s: Strings):
    text = await get_default_template("welcome", s("welcome_default"))
    await m.reply_text(text, parse_mode=ParseMode.DISABLED)


@Client.on_message(filters.command("getdefaultgoodbye", PREFIXES) & sudofilter)
@use_chat_lang
async def get_default_goodbye_message(c: Client, m: Message, s: Strings):
    text = await get_default_template("goodbye", s("goodbye_default"))
    await m.reply_text(text, parse_mode=ParseMode.DISABLED)


@Client.on_message(filters.command("welcome on", PREFIXES) & filters.group)
@require_admin(ChatPrivileges(can_change_info=True))
@use_chat_lang
async def enable_welcome_message(c: Client, m: Message, s: Strings):
    await toggle_welcome(m.chat.id, True)
    await m.reply_text(s("welcome_mode_enable").format(chat_title=escape(m.chat.title or "")))


@Client.on_message(filters.command("welcome off", PREFIXES) & filters.group)
@require_admin(ChatPrivileges(can_change_info=True))
@use_chat_lang
async def disable_welcome_message(c: Client, m: Message, s: Strings):
    await toggle_welcome(m.chat.id, False)
    await m.reply_text(s("welcome_mode_disable").format(chat_title=escape(m.chat.title or "")))


@Client.on_message(filters.command("goodbye on", PREFIXES) & filters.group)
@require_admin(ChatPrivileges(can_change_info=True))
@use_chat_lang
async def enable_goodbye_message(c: Client, m: Message, s: Strings):
    await toggle_goodbye(m.chat.id, True)
    await m.reply_text(s("goodbye_mode_enable").format(chat_title=escape(m.chat.title or "")))


@Client.on_message(filters.command("goodbye off", PREFIXES) & filters.group)
@require_admin(ChatPrivileges(can_change_info=True))
@use_chat_lang
async def disable_goodbye_message(c: Client, m: Message, s: Strings):
    await toggle_goodbye(m.chat.id, False)
    await m.reply_text(s("goodbye_mode_disable").format(chat_title=escape(m.chat.title or "")))


@Client.on_message(filters.command("welcomedelete", PREFIXES) & filters.group)
@require_admin(ChatPrivileges(can_change_info=True))
@use_chat_lang
async def set_welcome_delete_delay(c: Client, m: Message, s: Strings):
    if len(m.command) == 1 or m.command[1].casefold() == "status":
        seconds = await get_greeting_delete_seconds(m.chat.id)
        state = s("general_disabled") if seconds <= 0 else f"{seconds}s"
        await m.reply_text(s("welcome_delete_status").format(state=state))
        return

    value = m.command[1].casefold()
    if value in {"off", "disable", "disabled", "none", "0"}:
        seconds = 0
    elif value in {"on", "enable", "enabled"}:
        seconds = DEFAULT_GREETING_DELETE_SECONDS
    elif value == "toggle":
        current_seconds = await get_greeting_delete_seconds(m.chat.id)
        seconds = 0 if current_seconds > 0 else DEFAULT_GREETING_DELETE_SECONDS
    elif value.isdigit():
        seconds = min(max(int(value), 1), 86400)
    else:
        await m.reply_text(s("welcome_delete_usage"))
        return

    await set_greeting_delete_seconds(m.chat.id, seconds)
    if seconds <= 0:
        await m.reply_text(s("welcome_delete_disabled"))
    else:
        await m.reply_text(s("welcome_delete_updated").format(seconds=seconds))


@Client.on_message(filters.command(["resetwelcome", "clearwelcome"], PREFIXES) & filters.group)
@require_admin(ChatPrivileges(can_change_info=True))
@use_chat_lang
async def reset_welcome_message(c: Client, m: Message, s: Strings):
    await set_welcome(m.chat.id, None, None, None)
    await m.reply_text(s("welcome_reset").format(chat_title=escape(m.chat.title or "")))


@Client.on_message(filters.command(["resetgoodbye", "cleargoodbye"], PREFIXES) & filters.group)
@require_admin(ChatPrivileges(can_change_info=True))
@use_chat_lang
async def reset_goodbye_message(c: Client, m: Message, s: Strings):
    await set_goodbye(m.chat.id, None, None, None)
    await m.reply_text(s("goodbye_reset").format(chat_title=escape(m.chat.title or "")))


@Client.on_message(filters.command("resetdefaultwelcome", PREFIXES) & sudofilter)
@use_chat_lang
async def reset_default_welcome_message(c: Client, m: Message, s: Strings):
    await reset_default_template("welcome")
    await m.reply_text(s("welcome_default_reset"))


@Client.on_message(filters.command("resetdefaultgoodbye", PREFIXES) & sudofilter)
@use_chat_lang
async def reset_default_goodbye_message(c: Client, m: Message, s: Strings):
    await reset_default_template("goodbye")
    await m.reply_text(s("goodbye_default_reset"))


for command in (
    "resetwelcome",
    "setwelcome",
    "getwelcome",
    "setdefaultwelcome",
    "getdefaultwelcome",
    "resetdefaultwelcome",
    "welcome",
    "welcomedelete",
    "welcomeformat",
    "resetgoodbye",
    "setgoodbye",
    "getgoodbye",
    "setdefaultgoodbye",
    "getdefaultgoodbye",
    "resetdefaultgoodbye",
    "goodbye",
    "goodbyeformat",
):
    commands.add_command(command, "admin_welcome")
