# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from __future__ import annotations

import re
from typing import Any, Literal

from hydrogram.types import InlineKeyboardButton

ButtonStyle = Literal["primary", "secondary", "success", "danger"]
TG_EMOJI_RE = re.compile(r'<tg-emoji\b[^>]*>(.*?)</tg-emoji>')


def button_text_fallback(text: str) -> str:
    return TG_EMOJI_RE.sub(r"\1", text)


def styled_button(
    text: str,
    *,
    style: ButtonStyle | None = None,
    **kwargs: Any,
) -> InlineKeyboardButton:
    text = button_text_fallback(text)
    if not style:
        return InlineKeyboardButton(text, **kwargs)
    try:
        button = InlineKeyboardButton(text, style=style, **kwargs)
    except TypeError:
        button = InlineKeyboardButton(text, **kwargs)
    button.style = style
    return button
