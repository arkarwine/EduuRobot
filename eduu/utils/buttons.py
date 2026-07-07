# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from __future__ import annotations

from typing import Any, Literal

from hydrogram.types import InlineKeyboardButton

ButtonStyle = Literal["primary", "secondary", "success", "danger"]


def styled_button(
    text: str,
    *,
    style: ButtonStyle | None = None,
    **kwargs: Any,
) -> InlineKeyboardButton:
    if not style:
        return InlineKeyboardButton(text, **kwargs)
    try:
        button = InlineKeyboardButton(text, style=style, **kwargs)
    except TypeError:
        button = InlineKeyboardButton(text, **kwargs)
    button.style = style
    return button
