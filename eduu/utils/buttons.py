# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from __future__ import annotations

import re
from typing import Any, Literal

from hydrogram.types import InlineKeyboardButton

ButtonStyle = Literal["primary", "secondary", "success", "danger"]
LEADING_TG_EMOJI_RE = re.compile(
    r'^\s*<tg-emoji\s+emoji-id=(["\'])(?P<emoji_id>\d+)\1>(?P<fallback>.*?)</tg-emoji>\s*'
)


def _parse_button_custom_emoji(text: str) -> tuple[str, str | None, str | None]:
    match = LEADING_TG_EMOJI_RE.match(text)
    if not match:
        return text, None, None

    fallback = match.group("fallback")
    label = text[match.end() :].lstrip()
    fallback_text = f"{fallback} {label}".strip()
    return fallback_text, label or fallback, match.group("emoji_id")


def styled_button(
    text: str,
    *,
    style: ButtonStyle | None = None,
    **kwargs: Any,
) -> InlineKeyboardButton:
    text, custom_emoji_text, custom_emoji_id = _parse_button_custom_emoji(text)
    if not style:
        button = InlineKeyboardButton(text, **kwargs)
    else:
        try:
            button = InlineKeyboardButton(text, style=style, **kwargs)
        except TypeError:
            button = InlineKeyboardButton(text, **kwargs)
    button.style = style
    if custom_emoji_id:
        button.icon_custom_emoji_id = custom_emoji_id
        button.custom_emoji_text = custom_emoji_text
    return button
