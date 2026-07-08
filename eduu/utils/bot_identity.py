# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from __future__ import annotations

_bot_name = "Bot"
_bot_username = ""


def cache_bot_identity(*, name: str | None, username: str | None) -> None:
    global _bot_name, _bot_username

    _bot_name = name or username or _bot_name
    _bot_username = username or _bot_username


def get_bot_name() -> str:
    return _bot_name


def get_bot_username() -> str:
    return _bot_username
