# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from hydrogram import Client, filters
from hydrogram.enums import ParseMode
from hydrogram.errors import BadRequest
from hydrogram.types import ChatPrivileges, InlineKeyboardMarkup, Message

from config import PREFIXES
from eduu.database.welcome import get_welcome, set_welcome, toggle_welcome
from eduu.utils import button_parser, commands, get_format_keys
from eduu.utils.decorators import require_admin, stop_here
from eduu.utils.localization import Strings, use_chat_lang


@Client.on_message(filters.command(["welcomeformat", "start welcome_format_help"], PREFIXES))
@use_chat_lang
@stop_here
async def welcome_format_message_help(c: Client, m: Message, s: Strings):
    await m.reply_text(s("welcome_format_help_msg"))


@Client.on_message(filters.command("setwelcome", PREFIXES) & filters.group)
@require_admin(ChatPrivileges(can_change_info=True))
@use_chat_lang
async def set_welcome_message(c: Client, m: Message, s: Strings):
    # Make this reply-based: reply to a message to set welcome text or media
    if not m.reply_to_message:
        await m.reply_text(
            s("welcome_set_empty").format(bot_username=c.me.username),
            disable_web_page_preview=True,
        )
        return

    src = m.reply_to_message

    # Determine media or text
    media_file_id = None
    media_type = None
    if src.photo:
        media_file_id = src.photo.file_id
        media_type = "photo"
        message = src.caption or None
    elif src.video:
        media_file_id = src.video.file_id
        media_type = "video"
        message = src.caption or None
    else:
        # Use text or caption
        message = src.text or src.caption or None

    if not message and not media_file_id:
        await m.reply_text(s("welcome_set_empty").format(bot_username=c.me.username))
        return

    # Validate/preview formatted message
    preview = message or ""
    try:
        preview_formatted = preview.format(
            id=m.from_user.id,
            username=m.from_user.username,
            mention=m.from_user.mention,
            first_name=m.from_user.first_name,
            full_name=m.from_user.full_name,
            name=m.from_user.first_name,
            title=m.chat.title,
            chat_title=m.chat.title,
            count=(await c.get_chat_members_count(m.chat.id)),
        ) if preview else ""
        sent = await m.reply_text(preview_formatted or s("welcome_set_success"))
    except (KeyError, BadRequest) as e:
        await m.reply_text(s("welcome_set_error").format(error=f"{e.__class__.__name__}: {e!s}"))
        return

    # Persist welcome text and media
    await set_welcome(m.chat.id, message, media_file_id, media_type)
    await sent.edit_text(s("welcome_set_success").format(chat_title=m.chat.title))


@Client.on_message(
    (filters.command("welcome") & ~filters.command(["welcome on", "welcome off"])) & filters.group
)
@require_admin(ChatPrivileges(can_change_info=True))
@use_chat_lang
async def invlaid_welcome_status_arg(c: Client, m: Message, s: Strings):
    await m.reply_text(s("welcome_mode_invalid"))


@Client.on_message(filters.command("getwelcome", PREFIXES) & filters.group)
@require_admin(ChatPrivileges(can_change_info=True))
@use_chat_lang
async def getwelcomemsg(c: Client, m: Message, s: Strings):
    welcome, welcome_enabled, media_file_id, media_type = await get_welcome(m.chat.id)
    if welcome_enabled:
        text = s("welcome_default") if welcome is None else welcome
        msg = f"{text}\n\n" + (f"[Media: {media_type}]" if media_file_id else "")
        await m.reply_text(msg, parse_mode=ParseMode.DISABLED)
    else:
        await m.reply_text("None")


@Client.on_message(filters.command("welcome on", PREFIXES) & filters.group)
@require_admin(ChatPrivileges(can_change_info=True))
@use_chat_lang
async def enable_welcome_message(c: Client, m: Message, s: Strings):
    await toggle_welcome(m.chat.id, True)
    await m.reply_text(s("welcome_mode_enable").format(chat_title=m.chat.title))


@Client.on_message(filters.command("welcome off", PREFIXES) & filters.group)
@require_admin(ChatPrivileges(can_change_info=True))
@use_chat_lang
async def disable_welcome_message(c: Client, m: Message, s: Strings):
    await toggle_welcome(m.chat.id, False)
    await m.reply_text(s("welcome_mode_disable").format(chat_title=m.chat.title))


@Client.on_message(filters.command(["resetwelcome", "clearwelcome"], PREFIXES) & filters.group)
@require_admin(ChatPrivileges(can_change_info=True))
@use_chat_lang
async def reset_welcome_message(c: Client, m: Message, s: Strings):
    await set_welcome(m.chat.id, None, None, None)
    await m.reply_text(s("welcome_reset").format(chat_title=m.chat.title))


@Client.on_message(filters.new_chat_members & filters.group)
@use_chat_lang
async def greet_new_members(c: Client, m: Message, s: Strings):
    if m.new_chat_members[0].is_bot:
        return

    welcome, welcome_enabled, media_file_id, media_type = await get_welcome(m.chat.id)
    if not welcome_enabled:
        return

    if welcome is None:
        welcome = s("welcome_default")

    if "count" in get_format_keys(welcome):
        count = await c.get_chat_members_count(m.chat.id)
    else:
        count = 0

    chat_title = m.chat.title
    members = m.new_chat_members
    mention = ", ".join(a.mention for a in members)
    username = ", ".join(f"@{a.username}" if a.username else a.mention for a in members)

    user_id = ", ".join(str(a.id) for a in members)
    full_name = ", ".join(f"{a.first_name} " + (a.last_name or "") for a in members)

    first_name = ", ".join(a.first_name for a in members)
    welcome = (welcome or s("welcome_default")).format(
        id=user_id,
        username=username,
        mention=mention,
        first_name=first_name,
        # full_name and name are the same
        full_name=full_name,
        name=full_name,
        # title and chat_title are the same
        title=chat_title,
        chat_title=chat_title,
        count=count,
    )
    welcome, welcome_buttons = button_parser(welcome)
    # Send media if configured
    reply_markup = InlineKeyboardMarkup(welcome_buttons) if len(welcome_buttons) != 0 else None
    try:
        if media_file_id and media_type == "photo":
            await c.send_photo(
                chat_id=m.chat.id,
                photo=media_file_id,
                caption=welcome,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
            return
        if media_file_id and media_type == "video":
            await c.send_video(
                chat_id=m.chat.id,
                video=media_file_id,
                caption=welcome,
                reply_markup=reply_markup,
                parse_mode=ParseMode.HTML,
            )
            return
    except Exception:
        # Fallback to text if media send fails
        pass

    await m.reply_text(
        welcome,
        disable_web_page_preview=True,
        reply_markup=reply_markup,
    )


commands.add_command("resetwelcome", "admin")
commands.add_command("setwelcome", "admin")
commands.add_command("welcome", "admin")
commands.add_command("welcomeformat", "admin")
