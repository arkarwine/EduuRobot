# SPDX-License-Identifier: MIT

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


def load_dotenv(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.is_absolute():
        env_path = Path(__file__).resolve().parents[2] / path
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("\"'")
        if key:
            os.environ.setdefault(key, value)


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return value.casefold() in {"1", "true", "yes", "y", "on", "enable", "enabled"}


def effective_disabled_plugins(
    configured_plugins: Iterable[str],
    *,
    auto_reply_enabled: bool = True,
    auto_download_enabled: bool = True,
) -> list[str]:
    disabled = []
    seen = set()
    for plugin in configured_plugins:
        if plugin not in seen:
            disabled.append(plugin)
            seen.add(plugin)
    for enabled, plugin in (
        (auto_reply_enabled, "autoreply"),
        (auto_download_enabled, "tiktok"),
    ):
        if not enabled and plugin not in seen:
            disabled.append(plugin)
            seen.add(plugin)
    return disabled
