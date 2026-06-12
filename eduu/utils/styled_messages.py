# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from __future__ import annotations

from typing import Any

from hydrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from config import TOKEN
from eduu.utils import http

BOT_API_URL = f"https://api.telegram.org/bot{TOKEN}"


def button_to_dict(button: InlineKeyboardButton) -> dict[str, Any]:
    data: dict[str, Any] = {"text": button.text}
    for field in (
        "callback_data",
        "url",
        "switch_inline_query",
        "switch_inline_query_current_chat",
    ):
        value = getattr(button, field, None)
        if value is not None:
            data[field] = value
            break
    if style := getattr(button, "style", None):
        data["style"] = style
    return data


def _markup_to_dict(markup: InlineKeyboardMarkup | None) -> dict[str, Any] | None:
    if markup is None:
        return None
    return {
        "inline_keyboard": [
            [button_to_dict(button) for button in row]
            for row in markup.inline_keyboard
        ]
    }


async def _request(method: str, payload: dict[str, Any]) -> dict[str, Any]:
    response = await http.post(f"{BOT_API_URL}/{method}", json=payload)
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("description", f"Bot API {method} failed"))
    return data["result"]


async def send_styled_text(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup,
) -> None:
    await _request(
        "sendMessage",
        {
            "chat_id": message.chat.id,
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": _markup_to_dict(reply_markup),
        },
    )


async def edit_styled_text(
    message: Message,
    text: str,
    reply_markup: InlineKeyboardMarkup | None,
    *,
    disable_web_page_preview: bool = False,
) -> None:
    if message.media:
        await _request(
            "editMessageCaption",
            {
                "chat_id": message.chat.id,
                "message_id": message.id,
                "caption": text,
                "parse_mode": "HTML",
                "reply_markup": _markup_to_dict(reply_markup),
            },
        )
        return

    await _request(
        "editMessageText",
        {
            "chat_id": message.chat.id,
            "message_id": message.id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": disable_web_page_preview,
            "reply_markup": _markup_to_dict(reply_markup),
        },
    )


async def send_styled_photo(
    message: Message,
    photo: str,
    caption: str,
    reply_markup: InlineKeyboardMarkup,
) -> None:
    await _request(
        "sendPhoto",
        {
            "chat_id": message.chat.id,
            "photo": photo,
            "caption": caption,
            "parse_mode": "HTML",
            "reply_markup": _markup_to_dict(reply_markup),
        },
    )


async def answer_styled_inline_query(
    inline_query_id: str,
    results: list[dict[str, Any]],
) -> None:
    await _request(
        "answerInlineQuery",
        {
            "inline_query_id": inline_query_id,
            "results": results,
            "cache_time": 0,
        },
    )
