# SPDX-License-Identifier: MIT

from __future__ import annotations

import asyncio
import random
from collections import defaultdict, deque
from html import escape
from time import monotonic

from hydrogram import Client, StopPropagation, filters
from hydrogram.enums import ParseMode
from hydrogram.errors import RPCError
from hydrogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from config import PREFIXES, SUDOERS
from eduu.database.autoreply import (
    GLOBAL_AUTOREPLY_ID,
    add_reaction,
    add_keyword_reaction,
    add_response,
    clear_keyword_reactions,
    clear_responses,
    clear_capture_state,
    delete_response,
    get_capture_state,
    get_response,
    get_reactions,
    get_keyword_reactions,
    get_responses,
    get_settings,
    remove_reaction,
    set_capture_state,
    set_setting,
)
from eduu.utils import commands, sudofilter
from eduu.utils.buttons import styled_button
from eduu.utils.decorators import stop_here
from eduu.utils.localization import Strings, use_chat_lang
from eduu.utils.styled_messages import edit_styled_text, send_styled_text

COOLDOWN_OPTIONS = [0, 5, 10, 15, 30, 60]
RATE_LIMIT_OPTIONS = [0, 5, 10, 20, 30]
CHANCE_OPTIONS = [0, 25, 50, 75, 100]
REPLIES_PER_PAGE = 10
MANAGER_DELETE_DELAY = 30
_last_interaction: dict[int, float] = {}
_recent_interactions: dict[int, deque[float]] = defaultdict(deque)


def _can_manage(user_id: int | None) -> bool:
    return bool(user_id and user_id in SUDOERS)


def _command_arg(m: Message) -> str:
    parts = (m.text or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) == 2 else ""


def _is_command(m: Message) -> bool:
    text = m.text or m.caption or ""
    return bool(text) and any(text.startswith(prefix) for prefix in PREFIXES)


def _normalize_keywords(value: str) -> list[str]:
    keywords = []
    for item in value.replace("\n", ",").split(","):
        keyword = " ".join(item.casefold().strip().split())
        if keyword and keyword not in keywords:
            keywords.append(keyword)
    return keywords


def _keyword_matches(text: str, keywords: list[str]) -> bool:
    haystack = " ".join(text.casefold().split())
    return bool(haystack and any(keyword in haystack for keyword in keywords))


def _message_label(message: Message) -> str:
    preview = " ".join((message.text or message.caption or "").split())
    if preview:
        return preview[:77] + "..." if len(preview) > 80 else preview
    if message.sticker:
        return "[sticker]"
    return f"[{str(message.media or 'message').split('.')[-1].lower()}]"


def _next_option(current: int, options: list[int]) -> int:
    try:
        return options[(options.index(current) + 1) % len(options)]
    except ValueError:
        return options[0]


def _interaction_allowed(chat_id: int, cooldown: int, per_minute: int) -> bool:
    now = monotonic()
    if cooldown and now - _last_interaction.get(chat_id, float("-inf")) < cooldown:
        return False
    recent = _recent_interactions[chat_id]
    while recent and now - recent[0] >= 60:
        recent.popleft()
    if per_minute and len(recent) >= per_minute:
        return False
    _last_interaction[chat_id] = now
    recent.append(now)
    return True


async def _delete_later(*messages: Message) -> None:
    await asyncio.sleep(MANAGER_DELETE_DELAY)
    for message in messages:
        try:
            await message.delete()
        except RPCError:
            pass


def _manager_keyboard(chat_id: int, settings: dict, s: Strings) -> InlineKeyboardMarkup:
    keyword_mode = settings["mode"] == "keyword"
    enabled_text = "⏸ Enabled" if settings["enabled"] else "▶️ Disabled"
    rows = [
        [
            styled_button(
                "🎯 Mode: Keyword" if keyword_mode else "🎲 Mode: Random",
                callback_data=f"mgr:mode:{chat_id}",
                style="primary",
            )
        ],
        [
            styled_button(
                "➕ Add Replies",
                callback_data=f"mgr:add:{chat_id}",
                style="success",
            ),
            styled_button(
                "📚 Replies",
                callback_data=f"mgr:list:{chat_id}",
                style="primary",
            ),
        ],
        [
            styled_button(
                "➕ Add Reactions",
                callback_data=f"mgr:add-reaction:{chat_id}",
                style="success",
            ),
            styled_button(
                "🎭 Reactions",
                callback_data=f"mgr:reaction-list:{chat_id}",
                style="primary",
            ),
        ],
        [
            styled_button(
                enabled_text,
                callback_data=f"mgr:toggle:{chat_id}",
                style="danger" if settings["enabled"] else "success",
            )
        ],
    ]
    if not keyword_mode:
        rows.extend(
            [
                [
                    styled_button(
                        f"Reply: {settings['reply_chance']}%",
                        callback_data=f"mgr:reply-chance:{chat_id}",
                        style="primary",
                    ),
                    styled_button(
                        f"React: {settings['reaction_chance']}%",
                        callback_data=f"mgr:chance:{chat_id}",
                        style="primary",
                    ),
                ],
                [
                    styled_button(
                        f"Cooldown: {settings['cooldown_seconds']}s",
                        callback_data=f"mgr:cooldown:{chat_id}",
                        style="primary",
                    ),
                    styled_button(
                        f"Rate: {settings['rate_limit_per_minute'] or '∞'}/min",
                        callback_data=f"mgr:rate:{chat_id}",
                        style="primary",
                    ),
                ],
            ]
        )
    rows.extend(
        [
            [
                styled_button(
                    "🗑 Clear Replies",
                    callback_data=f"mgr:confirm-clear:{chat_id}",
                    style="danger",
                ),
                styled_button(
                    "🎭 Clear Reactions",
                    callback_data=f"mgr:confirm-clear-reactions:{chat_id}",
                    style="danger",
                ),
            ],
            [
                styled_button(
                    "🔄 Refresh",
                    callback_data=f"mgr:open:{chat_id}",
                    style="success",
                )
            ],
        ]
    )
    return InlineKeyboardMarkup(rows)


def _saved_reply_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                styled_button(
                    "➕ Add Another",
                    callback_data=f"mgr:add:{chat_id}",
                    style="success",
                ),
                styled_button(
                    "📚 Replies",
                    callback_data=f"mgr:list:{chat_id}",
                    style="primary",
                ),
            ],
            [
                styled_button(
                    "⬅️ Manager",
                    callback_data=f"mgr:open:{chat_id}",
                    style="danger",
                )
            ],
        ]
    )


async def _manager_content(s: Strings) -> tuple[str, InlineKeyboardMarkup]:
    chat_id = GLOBAL_AUTOREPLY_ID
    settings = await get_settings(chat_id)
    responses = await get_responses(chat_id)
    random_count = len([response for response in responses if response["mode"] == "random"])
    keyword_count = len([response for response in responses if response["mode"] == "keyword"])
    keyword_reaction_count = len(await get_keyword_reactions(chat_id))
    rate = settings["rate_limit_per_minute"] or "∞"
    active = "🟢 Active" if settings["enabled"] else "🔴 Paused"
    if settings["mode"] == "keyword":
        text = (
            "⚙️ Global Auto Replies\n"
            "Mode: 🎯 Keyword\n"
            "Applies to every group the bot serves.\n\n"
            f"{active}  •  📚 {keyword_count} keyword replies\n"
            f"🎭 {keyword_reaction_count} keyword reactions\n\n"
            "Replies and reactions trigger only when a configured keyword matches."
        )
    else:
        text = (
            "⚙️ Global Auto Replies\n"
            "Mode: 🎲 Random\n"
            "Applies to every group the bot serves.\n\n"
            f"{active}  •  📚 {random_count} random replies\n"
            f"💬 Reply: {settings['reply_chance']}%  •  "
            f"🎲 React: {settings['reaction_chance']}%\n"
            f"⏱ Cooldown: {settings['cooldown_seconds']}s  •  🚦 Rate: {rate}/min"
        )
    return text, _manager_keyboard(chat_id, settings, s)


async def _reply_list_content(
    chat_id: int,
    page: int,
    mode: str | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    if mode is None:
        mode = (await get_settings(chat_id))["mode"]
    responses = await get_responses(chat_id, mode)
    page_count = max(1, (len(responses) + REPLIES_PER_PAGE - 1) // REPLIES_PER_PAGE)
    page = max(0, min(page, page_count - 1))
    page_items = responses[page * REPLIES_PER_PAGE : (page + 1) * REPLIES_PER_PAGE]
    lines = []
    buttons = []
    for response in page_items:
        keywords = ", ".join(response["keywords"])
        label = escape(response["label"] or response["response_type"])
        if keywords:
            label = f"{escape(keywords)} -> {label}"
        lines.append(f"{response['id']}. {label}")
        buttons.append(
            [
                styled_button(
                    f"👁 {response['id']}",
                    callback_data=f"mgr:preview-{response['id']}-{page}:{chat_id}",
                    style="primary",
                ),
                styled_button(
                    f"🗑 {response['id']}",
                    callback_data=f"mgr:delete-{response['id']}-{page}:{chat_id}",
                    style="danger",
                ),
            ]
        )
    title = "🎯 Keyword replies" if mode == "keyword" else "🎲 Random replies"
    text = f"{title} • {page + 1}/{page_count}\n\n" + "\n".join(lines) if lines else (
        f"📭 No {mode} replies yet."
    )
    navigation = []
    if page > 0:
        navigation.append(
            styled_button(
                "⬅️ Prev",
                callback_data=f"mgr:list-{page - 1}:{chat_id}",
                style="primary",
            )
        )
    if page + 1 < page_count:
        navigation.append(
            styled_button(
                "Next ➡️",
                callback_data=f"mgr:list-{page + 1}:{chat_id}",
                style="primary",
            )
        )
    if navigation:
        buttons.append(navigation)
    buttons.append(
        [styled_button("⬅️ Manager", callback_data=f"mgr:open:{chat_id}", style="danger")]
    )
    return text[:4096], InlineKeyboardMarkup(buttons)


async def _reaction_list_content(
    chat_id: int,
    mode: str | None = None,
) -> tuple[str, InlineKeyboardMarkup]:
    if mode is None:
        mode = (await get_settings(chat_id))["mode"]
    rows = []
    lines = []
    if mode == "keyword":
        title = "🎭 Keyword reactions"
        keyword_reactions = await get_keyword_reactions(chat_id)
        for entry in keyword_reactions:
            lines.append(f"{', '.join(entry['keywords'])} -> {entry['reaction']}")
    else:
        title = "🎭 Random reactions"
        reactions = await get_reactions(chat_id)
        lines = list(reactions)
        rows.extend(
            [
                [
                    styled_button(
                        f"🗑 {reaction}",
                        callback_data=f"mgr:delete-reaction-{reaction}:{chat_id}",
                        style="danger",
                    )
                ]
                for reaction in reactions
            ]
        )
    rows.append(
        [styled_button("⬅️ Manager", callback_data=f"mgr:open:{chat_id}", style="danger")]
    )
    body = "\n".join(lines) if lines else f"No {mode} reactions yet."
    return f"{title}\n\n{body}", InlineKeyboardMarkup(rows)


async def _send_response(c: Client, m: Message, response: dict) -> bool:
    try:
        if response["response_type"] == "text":
            await m.reply_text(
                response["text"],
                quote=True,
                parse_mode=ParseMode.DISABLED,
            )
            return True
        source = await c.get_messages(response["source_chat_id"], response["source_message_id"])
        if not source:
            return False
        await source.copy(m.chat.id, reply_to_message_id=m.id)
        return True
    except RPCError:
        return False


async def _maybe_react(m: Message, settings: dict, reactions: list[str]) -> None:
    if not settings["reactions_enabled"] or not reactions:
        return
    if random.randint(1, 100) > int(settings["reaction_chance"]):
        return
    try:
        await m.react(random.choice(reactions))
    except RPCError:
        pass


async def _maybe_keyword_react(m: Message, text: str) -> None:
    matches = [
        entry["reaction"]
        for entry in await get_keyword_reactions(GLOBAL_AUTOREPLY_ID)
        if _keyword_matches(text, entry["keywords"])
    ]
    if not matches:
        return
    try:
        await m.react(random.choice(matches))
    except RPCError:
        pass


@Client.on_message(filters.command("autoreply", PREFIXES) & sudofilter)
@use_chat_lang
async def autoreply_settings(c: Client, m: Message, s: Strings):
    arg = _command_arg(m)
    if not arg:
        if m.chat.type.name in {"PRIVATE", "BOT"}:
            text, keyboard = await _manager_content(s)
            await send_styled_text(m, text, keyboard)
        else:
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        styled_button(
                            "⚙️ Open Global Auto Reply Manager",
                            url=f"https://t.me/{c.me.username}?start=autoreply_global",
                            style="primary",
                        )
                    ]
                ]
            )
            await send_styled_text(
                m,
                "⚙️ Configure global auto replies in private chat.",
                keyboard,
            )
            asyncio.create_task(_delete_later(m))
        return

    parts = arg.split()
    key = parts[0].casefold()
    if key in {"on", "off"}:
        await set_setting(GLOBAL_AUTOREPLY_ID, "enabled", int(key == "on"))
    elif key == "mode" and len(parts) == 2 and parts[1] in {"random", "keyword"}:
        await set_setting(GLOBAL_AUTOREPLY_ID, "mode", parts[1])
    elif key == "chance" and len(parts) == 2 and parts[1].isdigit():
        await set_setting(GLOBAL_AUTOREPLY_ID, "reply_chance", min(max(int(parts[1]), 0), 100))
    elif key == "cooldown" and len(parts) == 2 and parts[1].isdigit():
        await set_setting(
            GLOBAL_AUTOREPLY_ID,
            "cooldown_seconds",
            min(max(int(parts[1]), 0), 3600),
        )
    elif key == "rate" and len(parts) == 2 and parts[1].isdigit():
        await set_setting(
            GLOBAL_AUTOREPLY_ID,
            "rate_limit_per_minute",
            min(max(int(parts[1]), 0), 120),
        )
    else:
        await m.reply_text(s("autoreply_usage"))
        return

    text, keyboard = await _manager_content(s)
    await send_styled_text(m, text, keyboard)


@Client.on_message(
    filters.command("start", PREFIXES)
    & filters.private
    & filters.regex(r"^/start autoreply_global$"),
    group=1,
)
@use_chat_lang
@stop_here
async def autoreply_start(c: Client, m: Message, s: Strings):
    if not _can_manage(m.from_user.id if m.from_user else None):
        await m.reply_text("⛔ Sudo users only.")
        return
    text, keyboard = await _manager_content(s)
    await send_styled_text(m, text, keyboard)


@Client.on_callback_query(filters.regex(r"^ar:"))
@use_chat_lang
async def autoreply_callback(c: Client, m: CallbackQuery, s: Strings):
    if not _can_manage(m.from_user.id if m.from_user else None):
        await m.answer("⛔ Sudo users only.", show_alert=True)
        return
    action = m.data.split(":", 1)[1]
    settings = await get_settings(GLOBAL_AUTOREPLY_ID)
    if action == "toggle":
        await set_setting(GLOBAL_AUTOREPLY_ID, "enabled", int(not settings["enabled"]))
    elif action == "mode":
        await set_setting(
            GLOBAL_AUTOREPLY_ID,
            "mode",
            "keyword" if settings["mode"] == "random" else "random",
        )
    elif action == "chance":
        await set_setting(
            GLOBAL_AUTOREPLY_ID,
            "reply_chance",
            _next_option(settings["reply_chance"], CHANCE_OPTIONS),
        )
    elif action == "cooldown":
        await set_setting(
            GLOBAL_AUTOREPLY_ID,
            "cooldown_seconds",
            _next_option(settings["cooldown_seconds"], COOLDOWN_OPTIONS),
        )
    elif action == "rate":
        await set_setting(
            GLOBAL_AUTOREPLY_ID,
            "rate_limit_per_minute",
            _next_option(settings["rate_limit_per_minute"], RATE_LIMIT_OPTIONS),
        )
    elif action == "reactions":
        await set_setting(
            GLOBAL_AUTOREPLY_ID,
            "reactions_enabled",
            int(not settings["reactions_enabled"]),
        )
    text, keyboard = await _manager_content(s)
    await edit_styled_text(m.message, text, keyboard)
    await m.answer("✅ Updated")


@Client.on_callback_query(filters.regex(r"^mgr:"))
@use_chat_lang
async def manager_callback(c: Client, m: CallbackQuery, s: Strings):
    if not m.from_user or not m.message:
        return
    try:
        action, raw_chat_id = m.data.removeprefix("mgr:").split(":", 1)
        chat_id = int(raw_chat_id)
    except (AttributeError, ValueError):
        await m.answer("⚠️ Invalid action.", show_alert=True)
        return
    chat_id = GLOBAL_AUTOREPLY_ID
    if not _can_manage(m.from_user.id):
        await m.answer("⛔ Sudo users only.", show_alert=True)
        return

    settings = await get_settings(chat_id)
    if action == "open":
        text, keyboard = await _manager_content(s)
        await edit_styled_text(m.message, text, keyboard)
        await m.answer()
        return
    if action == "add":
        if settings["mode"] == "keyword":
            await set_capture_state(
                m.from_user.id,
                chat_id=chat_id,
                keyword_prompt=True,
            )
            await m.message.reply_text(
                "🎯 Send the keyword or comma-separated keywords for this reply.\n\n"
                "/cancel to stop."
            )
        else:
            await set_capture_state(m.from_user.id, chat_id=chat_id)
            await m.message.reply_text("➕ Send the reply to save.\n\n/cancel to stop.")
        await m.answer("📥 Waiting for reply…")
        return
    if action == "add-reaction":
        if settings["mode"] == "keyword":
            await set_capture_state(
                m.from_user.id,
                chat_id=chat_id,
                keyword_prompt=True,
                reaction_prompt=True,
            )
            await m.message.reply_text(
                "🎯 Send the keyword or comma-separated keywords for this reaction.\n\n"
                "/cancel to stop."
            )
        else:
            await set_capture_state(m.from_user.id, chat_id=chat_id, reaction=True)
            await m.message.reply_text("🎭 Send the reaction emoji to save.\n\n/cancel to stop.")
        await m.answer("📥 Waiting for reaction…")
        return
    if action == "toggle":
        await set_setting(chat_id, "enabled", int(not settings["enabled"]))
    elif action == "mode":
        await set_setting(chat_id, "mode", "keyword" if settings["mode"] == "random" else "random")
    elif action == "reply-chance":
        await set_setting(
            chat_id,
            "reply_chance",
            _next_option(settings["reply_chance"], CHANCE_OPTIONS),
        )
    elif action == "chance":
        await set_setting(
            chat_id,
            "reaction_chance",
            _next_option(settings["reaction_chance"], CHANCE_OPTIONS),
        )
    elif action == "cooldown":
        await set_setting(
            chat_id,
            "cooldown_seconds",
            _next_option(settings["cooldown_seconds"], COOLDOWN_OPTIONS),
        )
    elif action == "rate":
        await set_setting(
            chat_id,
            "rate_limit_per_minute",
            _next_option(settings["rate_limit_per_minute"], RATE_LIMIT_OPTIONS),
        )
    elif action == "reaction-list":
        text, keyboard = await _reaction_list_content(chat_id, settings["mode"])
        await edit_styled_text(m.message, text, keyboard)
        await m.answer()
        return
    elif action == "confirm-clear":
        await send_styled_text(
            m.message,
            "🗑 Clear replies?",
            InlineKeyboardMarkup(
                [
                    [
                        styled_button(
                            "🗑 Clear",
                            callback_data=f"mgr:clear:{chat_id}",
                            style="danger",
                        ),
                        styled_button(
                            "✖️ Cancel",
                            callback_data=f"mgr:open:{chat_id}",
                            style="primary",
                        ),
                    ]
                ]
            ),
        )
        await m.answer()
        return
    elif action == "confirm-clear-reactions":
        await send_styled_text(
            m.message,
            "🎭 Clear reactions?",
            InlineKeyboardMarkup(
                [
                    [
                        styled_button(
                            "🎭 Clear",
                            callback_data=f"mgr:clear-reactions:{chat_id}",
                            style="danger",
                        ),
                        styled_button(
                            "✖️ Cancel",
                            callback_data=f"mgr:open:{chat_id}",
                            style="primary",
                        ),
                    ]
                ]
            ),
        )
        await m.answer()
        return
    elif action == "clear":
        await clear_responses(chat_id, settings["mode"])
    elif action == "clear-reactions":
        if settings["mode"] == "keyword":
            await clear_keyword_reactions(chat_id)
        else:
            for reaction in await get_reactions(chat_id):
                await remove_reaction(chat_id, reaction)
    elif action.startswith("list"):
        try:
            page = int(action.split("-", 1)[1]) if "-" in action else 0
        except ValueError:
            page = 0
        text, keyboard = await _reply_list_content(chat_id, page, settings["mode"])
        await edit_styled_text(m.message, text, keyboard)
        await m.answer()
        return
    elif action.startswith("preview-"):
        try:
            raw_id, raw_page = action.removeprefix("preview-").split("-", 1)
            response_id = int(raw_id)
            page = int(raw_page)
        except ValueError:
            await m.answer("⚠️ Reply not found.", show_alert=True)
            return
        response = await get_response(chat_id, response_id)
        if not response:
            await m.answer("⚠️ Reply not found.", show_alert=True)
            return
        await _send_response(c, m.message, response)
        await send_styled_text(
            m.message,
            f"👁 Reply {response_id}",
            InlineKeyboardMarkup(
                [
                    [
                        styled_button(
                            "⬅️ Back",
                            callback_data=f"mgr:list-{page}:{chat_id}",
                            style="danger",
                        ),
                        styled_button(
                            "🗑 Delete",
                            callback_data=f"mgr:delete-{response_id}-{page}:{chat_id}",
                            style="danger",
                        ),
                    ]
                ]
            ),
        )
        await m.answer()
        return
    elif action.startswith("delete-reaction-"):
        reaction = action.removeprefix("delete-reaction-")
        await remove_reaction(chat_id, reaction)
        text, keyboard = await _reaction_list_content(chat_id, settings["mode"])
        await edit_styled_text(m.message, text, keyboard)
        await m.answer("🗑 Deleted")
        return
    elif action.startswith("delete-"):
        try:
            raw_id, raw_page = action.removeprefix("delete-").split("-", 1)
            response_id = int(raw_id)
            page = int(raw_page)
        except ValueError:
            await m.answer("⚠️ Invalid reply.", show_alert=True)
            return
        await delete_response(chat_id, response_id)
        text, keyboard = await _reply_list_content(chat_id, page, settings["mode"])
        await edit_styled_text(m.message, text, keyboard)
        await m.answer("🗑 Deleted")
        return

    text, keyboard = await _manager_content(s)
    await edit_styled_text(m.message, text, keyboard)
    await m.answer("✅ Updated")


@Client.on_message(filters.command("addreply", PREFIXES) & sudofilter)
@use_chat_lang
async def add_autoreply(c: Client, m: Message, s: Strings):
    settings = await get_settings(GLOBAL_AUTOREPLY_ID)
    arg = _command_arg(m)
    mode = settings["mode"]
    keywords = None
    text = arg

    if mode == "keyword":
        if "|" in arg:
            raw_keywords, text = [part.strip() for part in arg.split("|", 1)]
            keywords = _normalize_keywords(raw_keywords)
        elif m.reply_to_message and arg:
            keywords = _normalize_keywords(arg)
            text = ""
        else:
            await m.reply_text(s("autoreply_add_keyword_usage"))
            return
        if not keywords:
            await m.reply_text(s("autoreply_add_keyword_usage"))
            return

    if m.reply_to_message:
        await add_response(
            GLOBAL_AUTOREPLY_ID,
            mode=mode,
            keywords=keywords,
            response_type="message",
            source_chat_id=m.reply_to_message.chat.id,
            source_message_id=m.reply_to_message.id,
            label=_message_label(m.reply_to_message),
        )
    elif text:
        await add_response(
            GLOBAL_AUTOREPLY_ID,
            mode=mode,
            keywords=keywords,
            response_type="text",
            text=text,
            label=text[:80],
        )
    else:
        await m.reply_text(s("autoreply_add_usage"))
        return

    await m.reply_text(s("autoreply_added"))


@Client.on_message(filters.command("replies", PREFIXES) & sudofilter)
@use_chat_lang
async def list_autoreplies(c: Client, m: Message, s: Strings):
    responses = await get_responses(GLOBAL_AUTOREPLY_ID)
    if not responses:
        await m.reply_text(s("autoreply_empty"))
        return
    lines = []
    for response in responses[:30]:
        keywords = ", ".join(response["keywords"])
        suffix = f" [{keywords}]" if keywords else ""
        lines.append(
            f"<code>{response['id']}</code>. <b>{response['mode']}</b>{suffix}: "
            f"{escape(response['label'] or response['response_type'])}"
        )
    await m.reply_text(s("autoreply_list").format(items="\n".join(lines)))


@Client.on_message(filters.command("delreply", PREFIXES) & sudofilter)
@use_chat_lang
async def delete_autoreply(c: Client, m: Message, s: Strings):
    if len(m.command) < 2 or not m.command[1].isdigit():
        await m.reply_text(s("autoreply_delete_usage"))
        return
    deleted = await delete_response(GLOBAL_AUTOREPLY_ID, int(m.command[1]))
    await m.reply_text(s("autoreply_deleted" if deleted else "autoreply_not_found"))


@Client.on_message(
    filters.command(["delete_replies", "delete_all_replies"], PREFIXES) & sudofilter
)
@use_chat_lang
async def clear_autoreplies(c: Client, m: Message, s: Strings):
    mode = (
        None
        if m.command[0] == "delete_all_replies"
        else (await get_settings(GLOBAL_AUTOREPLY_ID))["mode"]
    )
    deleted = await clear_responses(GLOBAL_AUTOREPLY_ID, mode)
    await m.reply_text(s("autoreply_cleared").format(count=deleted))


@Client.on_message(filters.command("reaction", PREFIXES) & sudofilter)
@use_chat_lang
async def reaction_settings(c: Client, m: Message, s: Strings):
    settings = await get_settings(GLOBAL_AUTOREPLY_ID)
    reactions = await get_reactions(GLOBAL_AUTOREPLY_ID)
    if len(m.command) == 1:
        await m.reply_text(
            s("autoreply_reaction_status").format(
                state=s("general_enabled")
                if settings["reactions_enabled"]
                else s("general_disabled"),
                chance=settings["reaction_chance"],
                reactions=", ".join(reactions),
            )
        )
        return
    key = m.command[1].casefold()
    if key in {"on", "off"}:
        await set_setting(GLOBAL_AUTOREPLY_ID, "reactions_enabled", int(key == "on"))
    elif key == "chance" and len(m.command) == 3 and m.command[2].isdigit():
        await set_setting(
            GLOBAL_AUTOREPLY_ID,
            "reaction_chance",
            min(max(int(m.command[2]), 0), 100),
        )
    elif key == "add" and len(m.command) == 3:
        await add_reaction(GLOBAL_AUTOREPLY_ID, m.command[2])
    elif key in {"del", "remove"} and len(m.command) == 3:
        await remove_reaction(GLOBAL_AUTOREPLY_ID, m.command[2])
    else:
        await m.reply_text(s("autoreply_reaction_usage"))
        return
    await m.reply_text(s("autoreply_reaction_updated"))


@Client.on_message(filters.private & filters.incoming, group=1)
async def capture_private_autoreply(c: Client, m: Message):
    if not m.from_user:
        return
    state = await get_capture_state(m.from_user.id)
    if not state:
        return
    text = (m.text or m.caption or "").strip()
    if text == "/cancel":
        await clear_capture_state(m.from_user.id)
        await m.reply_text("Cancelled.")
        raise StopPropagation
    if _is_command(m):
        return

    chat_id = GLOBAL_AUTOREPLY_ID
    if not _can_manage(m.from_user.id):
        await clear_capture_state(m.from_user.id)
        await m.reply_text("⛔ Sudo users only.")
        raise StopPropagation

    if state.get("capture_keyword_prompt"):
        keywords = _normalize_keywords(text)
        if not keywords:
            await m.reply_text(
                "⚠️ Send at least one keyword, separated with commas if needed."
            )
            raise StopPropagation
        await set_capture_state(
            m.from_user.id,
            chat_id=chat_id,
            keywords=keywords,
            reaction=state.get("capture_reaction_prompt"),
        )
        if state.get("capture_reaction_prompt"):
            await m.reply_text(
                "🎭 Now send the reaction emoji for those keywords.\n\n/cancel to stop."
            )
        else:
            await m.reply_text(
                "➕ Now send the reply message for those keywords.\n\n/cancel to stop."
            )
        raise StopPropagation

    if state.get("capture_reaction"):
        reaction = text
        if not reaction:
            await m.reply_text("⚠️ Send the reaction as text.")
            raise StopPropagation
        if state.get("capture_keywords"):
            await add_keyword_reaction(chat_id, state["capture_keywords"], reaction)
        else:
            await add_reaction(chat_id, reaction)
        await clear_capture_state(m.from_user.id)
        await send_styled_text(m, "✅ Reaction saved.", _saved_reply_keyboard(chat_id))
        raise StopPropagation

    if m.text:
        await add_response(
            chat_id,
            mode=(await get_settings(chat_id))["mode"],
            keywords=state.get("capture_keywords"),
            response_type="text",
            text=m.text,
            label=_message_label(m),
        )
    else:
        await add_response(
            chat_id,
            mode=(await get_settings(chat_id))["mode"],
            keywords=state.get("capture_keywords"),
            response_type="message",
            source_chat_id=m.chat.id,
            source_message_id=m.id,
            label=_message_label(m),
        )
    await clear_capture_state(m.from_user.id)
    await send_styled_text(
        m,
        "✅ Keyword reply saved." if state.get("capture_keywords") else "✅ Reply saved.",
        _saved_reply_keyboard(chat_id),
    )
    raise StopPropagation


@Client.on_message(filters.group & filters.incoming & ~filters.service, group=5)
async def serve_autoreply(c: Client, m: Message):
    if not m.from_user or m.from_user.is_bot or _is_command(m):
        return

    settings = await get_settings(GLOBAL_AUTOREPLY_ID)
    if not settings["enabled"]:
        return

    text = m.text or m.caption or ""
    responses = await get_responses(GLOBAL_AUTOREPLY_ID, settings["mode"])
    matched = (
        [response for response in responses if _keyword_matches(text, response["keywords"])]
        if settings["mode"] == "keyword"
        else responses
    )
    if settings["mode"] == "keyword":
        await _maybe_keyword_react(m, text)
    if not matched:
        if settings["mode"] == "random":
            await _maybe_react(m, settings, await get_reactions(GLOBAL_AUTOREPLY_ID))
        return

    if settings["mode"] == "random":
        if random.randint(1, 100) > int(settings["reply_chance"]):
            await _maybe_react(m, settings, await get_reactions(GLOBAL_AUTOREPLY_ID))
            return
        if not _interaction_allowed(
            m.chat.id,
            int(settings["cooldown_seconds"]),
            int(settings["rate_limit_per_minute"]),
        ):
            return

    await _send_response(c, m, random.choice(matched))
    await _maybe_react(m, settings, await get_reactions(GLOBAL_AUTOREPLY_ID))
    raise StopPropagation


for command in (
    "autoreply",
    "addreply",
    "replies",
    "delreply",
    "delete_replies",
    "delete_all_replies",
    "reaction",
):
    commands.add_command(command, "admin_autoreply")
