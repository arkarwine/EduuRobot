# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from __future__ import annotations

import logging
import random
from collections import defaultdict, deque
from time import monotonic

from hydrogram import Client, filters
from hydrogram.enums import ChatType
from hydrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import PREFIXES
from eduu.database import auto_reply as auto_reply_db
from eduu.utils import commands
from eduu.utils.buttons import styled_button
from eduu.utils.decorators import require_admin
from eduu.utils.localization import Strings, use_chat_lang

LOGGER = logging.getLogger(__name__)

_last_interaction: dict[int, float] = {}
_recent_interactions: dict[int, deque[float]] = defaultdict(deque)


def _interaction_allowed(chat_id: int, cooldown: int, per_minute: int, now: float | None = None) -> bool:
    current = monotonic if now is None else now
    if cooldown and current() - _last_interaction.get(chat_id, float("-inf")) < cooldown:
        return False
    recent = _recent_interactions[chat_id]
    while recent and current() - recent[0] >= 60:
        recent.popleft()
    if per_minute and len(recent) >= per_minute:
        return False
    _last_interaction[chat_id] = current()
    recent.append(current())
    return True


def _chance_succeeds(chance: int) -> bool:
    return random.randint(1, 100) <= chance


def _next_option(current: int | None, options: list[int]) -> int:
    if current in options:
        index = options.index(current)
        return options[(index + 1) % len(options)]
    return options[0]


def manager_keyboard(chat_id: int, settings: dict) -> InlineKeyboardMarkup:
    enabled = bool(settings.get("enabled"))
    rows: list[list[InlineKeyboardButton]] = [
        [
            styled_button(
                "🟢 On" if enabled else "🔴 Off",
                callback_data=f"autoreply:toggle:{chat_id}",
                style="success" if enabled else "danger",
            )
        ],
        [
            styled_button(
                "➕ Add Replies",
                callback_data=f"autoreply:add:{chat_id}",
                style="primary",
            ),
            styled_button(
                "📚 Replies",
                callback_data=f"autoreply:list:{chat_id}",
                style="primary",
            ),
        ],
        [
            styled_button(
                "➕ Add Reactions",
                callback_data=f"autoreply:add-reaction:{chat_id}",
                style="primary",
            ),
            styled_button(
                "🎭 Reactions",
                callback_data=f"autoreply:reaction-list:{chat_id}",
                style="primary",
            ),
        ],
        [
            styled_button(
                f"💬 Reply: {settings.get('reply_chance', auto_reply_db.DEFAULT_REPLY_CHANCE)}%",
                callback_data=f"autoreply:reply-chance:{chat_id}",
            ),
            styled_button(
                f"🎲 React: {settings.get('reaction_chance', auto_reply_db.DEFAULT_REACTION_CHANCE)}%",
                callback_data=f"autoreply:reaction-chance:{chat_id}",
            ),
        ],
        [
            styled_button(
                f"⏱ {settings.get('cooldown_seconds', auto_reply_db.DEFAULT_COOLDOWN_SECONDS)}s",
                callback_data=f"autoreply:cooldown:{chat_id}",
            ),
            styled_button(
                f"🚦 {settings.get('rate_limit_per_minute', auto_reply_db.DEFAULT_RATE_LIMIT_PER_MINUTE) or '∞'}/min",
                callback_data=f"autoreply:rate:{chat_id}",
            ),
        ],
        [
            styled_button(
                "🗑 Clear Replies",
                callback_data=f"autoreply:clear:{chat_id}",
                style="danger",
            ),
            styled_button(
                "🎭 Clear Reactions",
                callback_data=f"autoreply:clear-reactions:{chat_id}",
                style="danger",
            ),
        ],
        [
            styled_button(
                "🔄 Refresh",
                callback_data=f"autoreply:open:{chat_id}",
                style="success",
            )
        ],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _show_menu(client: Client, message: Message | CallbackQuery, s: Strings, settings: dict) -> None:
    chat = message.message.chat if isinstance(message, CallbackQuery) else message.chat
    chat_id = chat.id
    replies = await auto_reply_db.get_responses(chat_id)
    reactions = await auto_reply_db.get_reactions(chat_id)
    status = s("autoreply_enabled") if settings.get("enabled") else s("autoreply_disabled")
    text = (
        f"<b>{s('autoreply_menu_title')}</b>\n\n"
        f"{status}\n"
        f"📚 {len(replies)} replies • 🎭 {len(reactions)} reactions\n"
        f"💬 {settings.get('reply_chance', auto_reply_db.DEFAULT_REPLY_CHANCE)}% • "
        f"🎲 {settings.get('reaction_chance', auto_reply_db.DEFAULT_REACTION_CHANCE)}% • "
        f"⏱ {settings.get('cooldown_seconds', auto_reply_db.DEFAULT_COOLDOWN_SECONDS)}s • "
        f"🚦 {settings.get('rate_limit_per_minute', auto_reply_db.DEFAULT_RATE_LIMIT_PER_MINUTE) or '∞'}/min\n\n"
        f"{s('autoreply_menu_hint')}"
    )
    keyboard = manager_keyboard(chat_id, settings)
    if isinstance(message, CallbackQuery):
        await message.message.edit_text(text, reply_markup=keyboard)
    else:
        await client.send_message(chat.id, text, reply_markup=keyboard)


@Client.on_message(filters.command("autoreply", PREFIXES) & filters.group)
@require_admin(allow_in_private=False)
@use_chat_lang
async def autoreply_manage(client: Client, message: Message, s: Strings):
    settings = await auto_reply_db.get_settings(message.chat.id)
    await _show_menu(client, message, s, settings)


@Client.on_callback_query(filters.regex(r"^autoreply:(toggle|clear|add|add-reaction|list|reaction-list|reply-chance|reaction-chance|cooldown|rate|clear-reactions|open):"))
@use_chat_lang
async def autoreply_menu_callback(client: Client, callback: CallbackQuery, s: Strings):
    chat_id = callback.message.chat.id
    action = callback.data.split(":", 2)[1]
    if action == "toggle":
        settings = await auto_reply_db.get_settings(chat_id)
        enabled = not settings.get("enabled")
        await auto_reply_db.set_enabled(chat_id, enabled)
        settings["enabled"] = enabled
        await _show_menu(client, callback, s, settings)
        return

    if action == "reply-chance":
        settings = await auto_reply_db.get_settings(chat_id)
        chance = _next_option(settings.get("reply_chance"), [0, 25, 50, 75, 100])
        await auto_reply_db.set_reply_chance(chat_id, chance)
        settings["reply_chance"] = chance
        await _show_menu(client, callback, s, settings)
        return

    if action == "reaction-chance":
        settings = await auto_reply_db.get_settings(chat_id)
        chance = _next_option(settings.get("reaction_chance"), [0, 25, 50, 75, 100])
        await auto_reply_db.set_reaction_chance(chat_id, chance)
        settings["reaction_chance"] = chance
        await _show_menu(client, callback, s, settings)
        return

    if action == "cooldown":
        settings = await auto_reply_db.get_settings(chat_id)
        cooldown = _next_option(settings.get("cooldown_seconds"), [0, 5, 10, 15, 30])
        await auto_reply_db.set_cooldown(chat_id, cooldown)
        settings["cooldown_seconds"] = cooldown
        await _show_menu(client, callback, s, settings)
        return

    if action == "rate":
        settings = await auto_reply_db.get_settings(chat_id)
        rate = _next_option(settings.get("rate_limit_per_minute"), [0, 5, 10, 20, 30])
        await auto_reply_db.set_rate_limit(chat_id, rate)
        settings["rate_limit_per_minute"] = rate
        await _show_menu(client, callback, s, settings)
        return

    if action == "add":
        await callback.answer(s("autoreply_add_usage"), show_alert=True)
        return

    if action == "add-reaction":
        await callback.answer("Use /addreaction in this group to save a reaction.", show_alert=True)
        return

    if action == "list":
        replies = await auto_reply_db.get_responses(chat_id)
        lines = ["📚 Stored replies", *[f"{index}. {entry['text']}" for index, entry in enumerate(replies, 1)]] or ["📚 Stored replies", "No replies yet."]
        await callback.message.edit_text("\n".join(lines[:10]), reply_markup=manager_keyboard(chat_id, await auto_reply_db.get_settings(chat_id)))
        await callback.answer()
        return

    if action == "reaction-list":
        reactions = await auto_reply_db.get_reactions(chat_id)
        lines = ["🎭 Stored reactions", *[f"{index}. {reaction}" for index, reaction in enumerate(reactions, 1)]] or ["🎭 Stored reactions", "No reactions yet."]
        await callback.message.edit_text("\n".join(lines[:10]), reply_markup=manager_keyboard(chat_id, await auto_reply_db.get_settings(chat_id)))
        await callback.answer()
        return

    if action == "clear":
        await auto_reply_db.clear_responses(chat_id)
        await callback.answer(s("autoreply_replies_cleared"), show_alert=True)
        await _show_menu(client, callback, s, await auto_reply_db.get_settings(chat_id))
        return

    if action == "clear-reactions":
        await auto_reply_db.clear_reactions(chat_id)
        await callback.answer(s("autoreply_reactions_cleared"), show_alert=True)
        await _show_menu(client, callback, s, await auto_reply_db.get_settings(chat_id))
        return

    if action == "open":
        await _show_menu(client, callback, s, await auto_reply_db.get_settings(chat_id))
        return

    await callback.answer()


@Client.on_message(filters.command("addreply", PREFIXES) & filters.group)
@require_admin(allow_in_private=False)
@use_chat_lang
async def add_reply(client: Client, message: Message, s: Strings):
    if message.reply_to_message:
        source = message.reply_to_message.text or message.reply_to_message.caption or ""
    else:
        source = message.text.split(maxsplit=1)[1].strip() if len(message.text.split(maxsplit=1)) > 1 else ""
    if not source:
        await message.reply_text(s("autoreply_add_usage"))
        return
    await auto_reply_db.add_response(message.chat.id, source)
    await message.reply_text(s("autoreply_added"))


@Client.on_message(filters.command("addreaction", PREFIXES) & filters.group)
@require_admin(allow_in_private=False)
@use_chat_lang
async def add_reaction(client: Client, message: Message, s: Strings):
    reaction = (message.reply_to_message.text or message.reply_to_message.caption or "").strip() if message.reply_to_message else ""
    if not reaction:
        reaction = message.text.split(maxsplit=1)[1].strip() if len(message.text.split(maxsplit=1)) > 1 else ""
    if not reaction:
        await message.reply_text("Send a reaction emoji or reply to a message with /addreaction.")
        return
    await auto_reply_db.add_reaction(message.chat.id, reaction)
    await message.reply_text("Reaction added.")


@Client.on_message(filters.command("clearreplies", PREFIXES) & filters.group)
@require_admin(allow_in_private=False)
@use_chat_lang
async def clear_replies(client: Client, message: Message, s: Strings):
    await auto_reply_db.clear_responses(message.chat.id)
    await message.reply_text(s("autoreply_replies_cleared"))


@Client.on_message(filters.command("clearreactions", PREFIXES) & filters.group)
@require_admin(allow_in_private=False)
@use_chat_lang
async def clear_reactions(client: Client, message: Message, s: Strings):
    await auto_reply_db.clear_reactions(message.chat.id)
    await message.reply_text(s("autoreply_reactions_cleared"))


@Client.on_message(filters.group & ~filters.service & ~filters.command & ~filters.bot, group=2)
async def handle_auto_reply(client: Client, message: Message):
    if not message.from_user or message.from_user.is_bot or message.chat.type not in {
        ChatType.GROUP,
        ChatType.SUPERGROUP,
    }:
        return

    settings = await auto_reply_db.get_settings(message.chat.id)
    if not settings.get("enabled"):
        return

    cooldown = int(settings.get("cooldown_seconds", 0) or 0)
    per_minute = int(settings.get("rate_limit_per_minute", 0) or 0)
    if not _interaction_allowed(message.chat.id, cooldown, per_minute):
        return

    if not _chance_succeeds(int(settings.get("reply_chance", 50) or 50)):
        return

    response = await auto_reply_db.next_response(message.chat.id)
    if not response:
        return

    try:
        await message.reply_text(response["text"], disable_web_page_preview=True)
    except Exception as exc:  # pragma: no cover - Telegram permissions can vary
        LOGGER.warning("Auto-reply failed in chat %s: %s", message.chat.id, exc)

    if settings.get("reactions_enabled") and _chance_succeeds(int(settings.get("reaction_chance", 25) or 25)):
        reactions = await auto_reply_db.get_reactions(message.chat.id)
        if reactions:
            try:
                await message.react(random.choice(reactions))
            except Exception as exc:  # pragma: no cover - Telegram permissions can vary
                LOGGER.info("Reaction failed for chat %s: %s", message.chat.id, exc)


commands.add_command("autoreply", "general")
commands.add_command("addreply", "general")
commands.add_command("addreaction", "general")
commands.add_command("clearreplies", "general")
commands.add_command("clearreactions", "general")
