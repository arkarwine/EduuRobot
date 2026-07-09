# SPDX-License-Identifier: MIT

from __future__ import annotations

import re
from html import unescape

TG_EMOJI_RE = re.compile(
    r"<tg-emoji\s+emoji-id=(['\"])(?P<emoji_id>\d+)\1>(?P<fallback>.*?)</tg-emoji>",
    re.IGNORECASE | re.DOTALL,
)
TEST_CUSTOM_EMOJI_ID = "5764638872000533034"
TEST_CUSTOM_EMOJI_FALLBACK = "📚"

_custom_emoji_enabled = True


def custom_emoji_enabled() -> bool:
    return _custom_emoji_enabled


def set_custom_emoji_enabled(enabled: bool) -> None:
    global _custom_emoji_enabled
    _custom_emoji_enabled = enabled


def strip_custom_emoji_tags(text: str) -> str:
    return TG_EMOJI_RE.sub(lambda match: unescape(match.group("fallback")), text)


def render_custom_emoji_text(text: str) -> str:
    if _custom_emoji_enabled:
        return text
    return strip_custom_emoji_tags(text)
