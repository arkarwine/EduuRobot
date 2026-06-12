# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from __future__ import annotations

from inspect import signature
from typing import Any, Literal

from hydrogram.types import InlineKeyboardButton

ButtonStyle = Literal["primary", "success", "danger"]
supports_button_style = "style" in signature(InlineKeyboardButton).parameters


def styled_button(
    text: str,
    *,
    style: ButtonStyle | None = None,
    **kwargs: Any,
) -> InlineKeyboardButton:
    # Omitting style uses Telegram's normal app-specific button appearance.
    if style and supports_button_style:
        kwargs["style"] = style
    button = InlineKeyboardButton(text, **kwargs)
    button.style = style
    return button
