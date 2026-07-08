# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from __future__ import annotations

import re

TG_EMOJI_RE = re.compile(r"(<tg-emoji\b[^>]*>.*?</tg-emoji>)", re.DOTALL)

CUSTOM_EMOJI_IDS = {
    "📚": "5764638872000533034",
    "🌐": "5769403725898584391",
    "📢": "6021418126061605425",
    "👤": "6035084557378654059",
    "💬": "6028346797368283073",
    "➕": "6037622221625626773",
    "🌐_autoreply": "6030400221232501136",
    "🛡": "6030445631921721471",
    "📣": "6039422865189638057",
    "⚠": "6032636795387121097",
    "🚫": "5983580310292402968",
    "🔇": "6039853100653612987",
    "📌": "6043896193887506430",
    "🔎": "6032850693348399258",
    "📝": "5888880224195581055",
    "📜": "6041923781696426657",
    "👋": "6041921818896372382",
    "⚒": "6030537007350944596",
    "🌐_remote": "5776233299424843260",
    "🔧": "6021792097454002931",
}


def custom_emoji(fallback: str, emoji_id: str) -> str:
    return f'<tg-emoji emoji-id="{emoji_id}">{fallback}</tg-emoji>'


CUSTOM_EMOJI_REPLACEMENTS = (
    ("🌐 Global auto", f"{custom_emoji('🌐', CUSTOM_EMOJI_IDS['🌐_autoreply'])} Global auto"),
    ("🌐 Global Auto", f"{custom_emoji('🌐', CUSTOM_EMOJI_IDS['🌐_autoreply'])} Global Auto"),
    ("🌐 Remote moderation", f"{custom_emoji('🌐', CUSTOM_EMOJI_IDS['🌐_remote'])} Remote moderation"),
    ("🌐 ဘာသာစကား", f"{custom_emoji('🌐', CUSTOM_EMOJI_IDS['🌐'])} ဘာသာစကား"),
    ("🌐 Language", f"{custom_emoji('🌐', CUSTOM_EMOJI_IDS['🌐'])} Language"),
    ("🛡️", custom_emoji("🛡️", CUSTOM_EMOJI_IDS["🛡"])),
    ("🛡", custom_emoji("🛡", CUSTOM_EMOJI_IDS["🛡"])),
    ("⚠️", custom_emoji("⚠️", CUSTOM_EMOJI_IDS["⚠"])),
    ("⚠", custom_emoji("⚠", CUSTOM_EMOJI_IDS["⚠"])),
    ("🛠️", custom_emoji("🛠️", CUSTOM_EMOJI_IDS["⚒"])),
    ("🛠", custom_emoji("🛠", CUSTOM_EMOJI_IDS["⚒"])),
    ("⚒️", custom_emoji("⚒️", CUSTOM_EMOJI_IDS["⚒"])),
    ("⚒", custom_emoji("⚒", CUSTOM_EMOJI_IDS["⚒"])),
    ("🔨", custom_emoji("🔨", CUSTOM_EMOJI_IDS["⚒"])),
    ("📚", custom_emoji("📚", CUSTOM_EMOJI_IDS["📚"])),
    ("📢", custom_emoji("📢", CUSTOM_EMOJI_IDS["📢"])),
    ("👤", custom_emoji("👤", CUSTOM_EMOJI_IDS["👤"])),
    ("💬", custom_emoji("💬", CUSTOM_EMOJI_IDS["💬"])),
    ("➕", custom_emoji("➕", CUSTOM_EMOJI_IDS["➕"])),
    ("📣", custom_emoji("📣", CUSTOM_EMOJI_IDS["📣"])),
    ("🚫", custom_emoji("🚫", CUSTOM_EMOJI_IDS["🚫"])),
    ("🔇", custom_emoji("🔇", CUSTOM_EMOJI_IDS["🔇"])),
    ("📌", custom_emoji("📌", CUSTOM_EMOJI_IDS["📌"])),
    ("🔎", custom_emoji("🔎", CUSTOM_EMOJI_IDS["🔎"])),
    ("📝", custom_emoji("📝", CUSTOM_EMOJI_IDS["📝"])),
    ("📜", custom_emoji("📜", CUSTOM_EMOJI_IDS["📜"])),
    ("👋", custom_emoji("👋", CUSTOM_EMOJI_IDS["👋"])),
    ("🔧", custom_emoji("🔧", CUSTOM_EMOJI_IDS["🔧"])),
    ("🌐", custom_emoji("🌐", CUSTOM_EMOJI_IDS["🌐"])),
)


def with_custom_emoji(text: str) -> str:
    if not text:
        return text

    parts = TG_EMOJI_RE.split(text)
    for index, part in enumerate(parts):
        if not part or part.startswith("<tg-emoji"):
            continue
        for old, new in CUSTOM_EMOJI_REPLACEMENTS:
            part = part.replace(old, new)
        parts[index] = part
    return "".join(parts)
