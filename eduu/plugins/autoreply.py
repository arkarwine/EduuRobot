# SPDX-License-Identifier: MIT

from __future__ import annotations

import asyncio
import random
from collections import defaultdict, deque
from html import escape
from time import monotonic

from hydrogram import Client, StopPropagation, filters
from hydrogram.enums import ChatMemberStatus, ParseMode
from hydrogram.errors import RPCError
from hydrogram.types import CallbackQuery, ChatPrivileges, InlineKeyboardMarkup, Message

from config import PREFIXES
from eduu.database.autoreply import (
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
from eduu.utils import commands
from eduu.utils.buttons import styled_button
from eduu.utils.decorators import require_admin, stop_here
from eduu.utils.localization import Strings, use_chat_lang
from eduu.utils.styled_messages import edit_styled_text

COOLDOWN_OPTIONS = [0, 5, 10, 15, 30, 60]
RATE_LIMIT_OPTIONS = [0, 5, 10, 20, 30]
CHANCE_OPTIONS = [0, 25, 50, 75, 100]
REPLIES_PER_PAGE = 10
MANAGER_DELETE_DELAY = 30
_last_interaction: dict[int, float] = {}
_recent_interactions: dict[int, deque[float]] = defaultdict(deque)


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


def _settings_text(settings: dict, s: Strings) -> str:
    enabled = s("general_enabled") if settings["enabled"] else s("general_disabled")
    reactions = (
        s("general_enabled") if settings["reactions_enabled"] else s("general_disabled")
    )
    rate = settings["rate_limit_per_minute"] or s("autoreply_unlimited")
    return s("autoreply_status").format(
        enabled=enabled,
        mode=settings["mode"],
        reply_chance=settings["reply_chance"],
        cooldown=settings["cooldown_seconds"],
        rate=rate,
        reactions=reactions,
        reaction_chance=settings["reaction_chance"],
    )


def _settings_keyboard(settings: dict, s: Strings) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                styled_button(
                    s(
                        "autoreply_disable_btn"
                        if settings["enabled"]
                        else "autoreply_enable_btn"
                    ),
                    callback_data="ar:toggle",
                    style="danger" if settings["enabled"] else "success",
                ),
                styled_button(
                    s("autoreply_mode_btn").format(mode=settings["mode"]),
                    callback_data="ar:mode",
                    style="primary",
                ),
            ],
            [
                styled_button(
                    s("autoreply_chance_btn").format(chance=settings["reply_chance"]),
                    callback_data="ar:chance",
                ),
                styled_button(
                    s("autoreply_cooldown_btn").format(seconds=settings["cooldown_seconds"]),
                    callback_data="ar:cooldown",
                ),
            ],
            [
                styled_button(
                    s("autoreply_rate_btn").format(
                        rate=settings["rate_limit_per_minute"] or s("autoreply_unlimited")
                    ),
                    callback_data="ar:rate",
                ),
                styled_button(
                    s("autoreply_reactions_btn").format(
                        state=s("general_enabled")
                        if settings["reactions_enabled"]
                        else s("general_disabled")
                    ),
                    callback_data="ar:reactions",
                ),
            ],
        ]
    )


async def _user_is_group_admin(c: Client, chat_id: int, user_id: int) -> bool:
    try:
        chat = await c.get_chat(chat_id)
        member = await chat.get_member(user_id)
    except RPCError:
        return False
    return member.status in {ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR}


async def _delete_later(*messages: Message) -> None:
    await asyncio.sleep(MANAGER_DELETE_DELAY)
    for message in messages:
        try:
            await message.delete()
        except RPCError:
            pass


def _manager_keyboard(chat_id: int, settings: dict, s: Strings) -> InlineKeyboardMarkup:
    keyword_mode = settings["mode"] == "keyword"
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
                "⏸ Enabled" if settings["enabled"] else "▶️ Disabled",
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
                    ),
                    styled_button(
                        f"React: {settings['reaction_chance']}%",
                        callback_data=f"mgr:chance:{chat_id}",
                    ),
                ],
                [
                    styled_button(
                        f"Cooldown: {settings['cooldown_seconds']}s",
                        callback_data=f"mgr:cooldown:{chat_id}",
                    ),
                    styled_button(
                        f"Rate: {settings['rate_limit_per_minute'] or '∞'}/min",
                        callback_data=f"mgr:rate:{chat_id}",
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


async def _manager_content(
    c: Client,
    chat_id: int,
    s: Strings,
) -> tuple[str, InlineKeyboardMarkup]:
    settings = await get_settings(chat_id)
    responses = await get_responses(chat_id)
    try:
        chat = await c.get_chat(chat_id)
        title = chat.title or str(chat_id)
    except RPCError:
        title = str(chat_id)
    rate = settings["rate_limit_per_minute"] or "∞"
    text = (
        f"⚙️ {escape(title)}\n\n"
        f"{'🟢 Active' if settings['enabled'] else '🔴 Paused'}  •  "
        f"📚 {len(responses)} local\n"
        f"💬 {settings['reply_chance']}%  •  "
        f"🎲 {settings['reaction_chance']}%  •  "
        f"⏱ {settings['cooldown_seconds']}s  •  🚦 {rate}/min"
    )
    return text, _manager_keyboard(chat_id, settings, s)


async def _reply_list_content(chat_id: int, page: int) -> tuple[str, InlineKeyboardMarkup]:
    responses = await get_responses(chat_id)
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
                ),
                styled_button(
                    f"🗑 {response['id']}",
                    callback_data=f"mgr:delete-{response['id']}-{page}:{chat_id}",
                    style="danger",
                ),
            ]
        )
    text = (
        f"📚 Replies • {page + 1}/{page_count}\n\n" + "\n".join(lines)
        if lines
        else "📭 No replies yet."
    )
    navigation = []
    if page > 0:
        navigation.append(
            styled_button("⬅️ Prev", callback_data=f"mgr:list-{page - 1}:{chat_id}")
        )
    if page + 1 < page_count:
        navigation.append(
            styled_button("Next ➡️", callback_data=f"mgr:list-{page + 1}:{chat_id}")
        )
    if navigation:
        buttons.append(navigation)
    buttons.append(
        [styled_button("⬅️ Manager", callback_data=f"mgr:open:{chat_id}", style="danger")]
    )
    return text[:4096], InlineKeyboardMarkup(buttons)


async def _reaction_list_content(chat_id: int) -> tuple[str, InlineKeyboardMarkup]:
    reactions = await get_reactions(chat_id)
    keyword_reactions = await get_keyword_reactions(chat_id)
    rows = [
        [
            styled_button(
                f"🗑 {reaction}",
                callback_data=f"mgr:delete-reaction-{reaction}:{chat_id}",
                style="danger",
            )
        ]
        for reaction in reactions
    ]
    lines = list(reactions)
    for entry in keyword_reactions:
        lines.append(f"{', '.join(entry['keywords'])} -> {entry['reaction']}")
    rows.append(
        [styled_button("⬅️ Manager", callback_data=f"mgr:open:{chat_id}", style="danger")]
    )
    return "🎭 Reactions\n\n" + "\n".join(lines), InlineKeyboardMarkup(rows)


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
        for entry in await get_keyword_reactions(m.chat.id)
        if _keyword_matches(text, entry["keywords"])
    ]
    if not matches:
        return
    try:
        await m.react(random.choice(matches))
    except RPCError:
        pass


@Client.on_message(filters.command("autoreply", PREFIXES) & filters.group)
@require_admin(ChatPrivileges(can_change_info=True))
@use_chat_lang
async def autoreply_settings(c: Client, m: Message, s: Strings):
    settings = await get_settings(m.chat.id)
    arg = _command_arg(m)
    if not arg:
        launcher = await m.reply_text(
            "⚙️ Configure auto replies in private chat.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        styled_button(
                            "⚙️ Open Auto Reply Manager",
                            url=f"https://t.me/{c.me.username}?start=configure_{m.chat.id}",
                            style="primary",
                        )
                    ]
                ]
            ),
        )
        asyncio.create_task(_delete_later(m, launcher))
        return

    parts = arg.split()
    key = parts[0].casefold()
    if key in {"on", "off"}:
        await set_setting(m.chat.id, "enabled", int(key == "on"))
    elif key == "mode" and len(parts) == 2 and parts[1] in {"random", "keyword"}:
        await set_setting(m.chat.id, "mode", parts[1])
    elif key == "chance" and len(parts) == 2 and parts[1].isdigit():
        await set_setting(m.chat.id, "reply_chance", min(max(int(parts[1]), 0), 100))
    elif key == "cooldown" and len(parts) == 2 and parts[1].isdigit():
        await set_setting(m.chat.id, "cooldown_seconds", min(max(int(parts[1]), 0), 3600))
    elif key == "rate" and len(parts) == 2 and parts[1].isdigit():
        await set_setting(m.chat.id, "rate_limit_per_minute", min(max(int(parts[1]), 0), 120))
    else:
        await m.reply_text(s("autoreply_usage"))
        return

    settings = await get_settings(m.chat.id)
    await m.reply_text(_settings_text(settings, s), reply_markup=_settings_keyboard(settings, s))


@Client.on_message(
    filters.command("start", PREFIXES)
    & filters.private
    & filters.regex(r"^/start configure_"),
    group=1,
)
@use_chat_lang
@stop_here
async def autoreply_start(c: Client, m: Message, s: Strings):
    arg = _command_arg(m)
    if not arg.startswith("configure_"):
        return
    try:
        chat_id = int(arg.removeprefix("configure_"))
    except ValueError:
        await m.reply_text("⚠️ Invalid group link.")
        return
    if not m.from_user or not await _user_is_group_admin(c, chat_id, m.from_user.id):
        await m.reply_text("⛔ Group admins only.")
        return
    text, keyboard = await _manager_content(c, chat_id, s)
    await m.reply_text(text, reply_markup=keyboard)


@Client.on_callback_query(filters.regex(r"^ar:"))
@require_admin(ChatPrivileges(can_change_info=True))
@use_chat_lang
async def autoreply_callback(c: Client, m: CallbackQuery, s: Strings):
    settings = await get_settings(m.message.chat.id)
    action = m.data.split(":", 1)[1]
    if action == "toggle":
        await set_setting(m.message.chat.id, "enabled", int(not settings["enabled"]))
    elif action == "mode":
        await set_setting(
            m.message.chat.id,
            "mode",
            "keyword" if settings["mode"] == "random" else "random",
        )
    elif action == "chance":
        await set_setting(
            m.message.chat.id,
            "reply_chance",
            _next_option(settings["reply_chance"], CHANCE_OPTIONS),
        )
    elif action == "cooldown":
        await set_setting(
            m.message.chat.id,
            "cooldown_seconds",
            _next_option(settings["cooldown_seconds"], COOLDOWN_OPTIONS),
        )
    elif action == "rate":
        await set_setting(
            m.message.chat.id,
            "rate_limit_per_minute",
            _next_option(settings["rate_limit_per_minute"], RATE_LIMIT_OPTIONS),
        )
    elif action == "reactions":
        await set_setting(
            m.message.chat.id,
            "reactions_enabled",
            int(not settings["reactions_enabled"]),
        )
    settings = await get_settings(m.message.chat.id)
    await edit_styled_text(m.message, _settings_text(settings, s), _settings_keyboard(settings, s))


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
    if not await _user_is_group_admin(c, chat_id, m.from_user.id):
        await m.answer("⛔ Group admins only.", show_alert=True)
        return

    settings = await get_settings(chat_id)
    if action == "open":
        text, keyboard = await _manager_content(c, chat_id, s)
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
        text, keyboard = await _reaction_list_content(chat_id)
        await edit_styled_text(m.message, text, keyboard)
        await m.answer()
        return
    elif action == "confirm-clear":
        await m.message.reply_text(
            "🗑 Clear replies?",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        styled_button(
                            "🗑 Clear",
                            callback_data=f"mgr:clear:{chat_id}",
                            style="danger",
                        ),
                        styled_button("✖️ Cancel", callback_data=f"mgr:open:{chat_id}"),
                    ]
                ]
            ),
        )
        await m.answer()
        return
    elif action == "confirm-clear-reactions":
        await m.message.reply_text(
            "🎭 Clear reactions?",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        styled_button(
                            "🎭 Clear",
                            callback_data=f"mgr:clear-reactions:{chat_id}",
                            style="danger",
                        ),
                        styled_button("✖️ Cancel", callback_data=f"mgr:open:{chat_id}"),
                    ]
                ]
            ),
        )
        await m.answer()
        return
    elif action == "clear":
        await clear_responses(chat_id, settings["mode"])
    elif action == "clear-reactions":
        for reaction in await get_reactions(chat_id):
            await remove_reaction(chat_id, reaction)
        await clear_keyword_reactions(chat_id)
    elif action.startswith("list"):
        try:
            page = int(action.split("-", 1)[1]) if "-" in action else 0
        except ValueError:
            page = 0
        text, keyboard = await _reply_list_content(chat_id, page)
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
        await m.message.reply_text(
            f"👁 Reply {response_id}",
            reply_markup=InlineKeyboardMarkup(
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
        text, keyboard = await _reaction_list_content(chat_id)
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
        text, keyboard = await _reply_list_content(chat_id, page)
        await edit_styled_text(m.message, text, keyboard)
        await m.answer("🗑 Deleted")
        return

    text, keyboard = await _manager_content(c, chat_id, s)
    await edit_styled_text(m.message, text, keyboard)
    await m.answer("✅ Updated")


@Client.on_message(filters.command("addreply", PREFIXES) & filters.group)
@require_admin(ChatPrivileges(can_change_info=True))
@use_chat_lang
async def add_autoreply(c: Client, m: Message, s: Strings):
    settings = await get_settings(m.chat.id)
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
            m.chat.id,
            mode=mode,
            keywords=keywords,
            response_type="message",
            source_chat_id=m.reply_to_message.chat.id,
            source_message_id=m.reply_to_message.id,
            label=_message_label(m.reply_to_message),
        )
    elif text:
        await add_response(
            m.chat.id,
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


@Client.on_message(filters.command("replies", PREFIXES) & filters.group)
@require_admin()
@use_chat_lang
async def list_autoreplies(c: Client, m: Message, s: Strings):
    responses = await get_responses(m.chat.id)
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


@Client.on_message(filters.command("delreply", PREFIXES) & filters.group)
@require_admin(ChatPrivileges(can_change_info=True))
@use_chat_lang
async def delete_autoreply(c: Client, m: Message, s: Strings):
    if len(m.command) < 2 or not m.command[1].isdigit():
        await m.reply_text(s("autoreply_delete_usage"))
        return
    deleted = await delete_response(m.chat.id, int(m.command[1]))
    await m.reply_text(s("autoreply_deleted" if deleted else "autoreply_not_found"))


@Client.on_message(
    filters.command(["delete_replies", "delete_all_replies"], PREFIXES) & filters.group
)
@require_admin(ChatPrivileges(can_change_info=True))
@use_chat_lang
async def clear_autoreplies(c: Client, m: Message, s: Strings):
    mode = (
        None
        if m.command[0] == "delete_all_replies"
        else (await get_settings(m.chat.id))["mode"]
    )
    deleted = await clear_responses(m.chat.id, mode)
    await m.reply_text(s("autoreply_cleared").format(count=deleted))


@Client.on_message(filters.command("reaction", PREFIXES) & filters.group)
@require_admin(ChatPrivileges(can_change_info=True))
@use_chat_lang
async def reaction_settings(c: Client, m: Message, s: Strings):
    settings = await get_settings(m.chat.id)
    reactions = await get_reactions(m.chat.id)
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
        await set_setting(m.chat.id, "reactions_enabled", int(key == "on"))
    elif key == "chance" and len(m.command) == 3 and m.command[2].isdigit():
        await set_setting(m.chat.id, "reaction_chance", min(max(int(m.command[2]), 0), 100))
    elif key == "add" and len(m.command) == 3:
        await add_reaction(m.chat.id, m.command[2])
    elif key in {"del", "remove"} and len(m.command) == 3:
        await remove_reaction(m.chat.id, m.command[2])
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

    chat_id = state.get("capture_chat_id")
    if not chat_id or not await _user_is_group_admin(c, chat_id, m.from_user.id):
        await clear_capture_state(m.from_user.id)
        await m.reply_text("⛔ Group admins only.")
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
        await m.reply_text("✅ Reaction saved.", reply_markup=_saved_reply_keyboard(chat_id))
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
    await m.reply_text(
        "✅ Keyword reply saved." if state.get("capture_keywords") else "✅ Reply saved.",
        reply_markup=_saved_reply_keyboard(chat_id),
    )
    raise StopPropagation


@Client.on_message(filters.group & filters.incoming & ~filters.service, group=5)
async def serve_autoreply(c: Client, m: Message):
    if not m.from_user or m.from_user.is_bot or _is_command(m):
        return

    settings = await get_settings(m.chat.id)
    if not settings["enabled"]:
        return

    text = m.text or m.caption or ""
    responses = await get_responses(m.chat.id, settings["mode"])
    matched = (
        [response for response in responses if _keyword_matches(text, response["keywords"])]
        if settings["mode"] == "keyword"
        else responses
    )
    if settings["mode"] == "keyword":
        await _maybe_keyword_react(m, text)
    if not matched:
        if settings["mode"] == "random":
            await _maybe_react(m, settings, await get_reactions(m.chat.id))
        return

    if settings["mode"] == "random":
        if random.randint(1, 100) > int(settings["reply_chance"]):
            await _maybe_react(m, settings, await get_reactions(m.chat.id))
            return
        if not _interaction_allowed(
            m.chat.id,
            int(settings["cooldown_seconds"]),
            int(settings["rate_limit_per_minute"]),
        ):
            return

    await _send_response(c, m, random.choice(matched))
    await _maybe_react(m, settings, await get_reactions(m.chat.id))
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
