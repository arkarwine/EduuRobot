# SPDX-License-Identifier: MIT

from __future__ import annotations

from hydrogram import filters

from config import SUDOERS, SUPER_SUDOERS

CONFIGURED_SUDOERS = frozenset(SUDOERS)
SUPER_SUDOER_IDS = frozenset(SUPER_SUDOERS)

sudofilter = filters.user(list(CONFIGURED_SUDOERS | SUPER_SUDOER_IDS))
super_sudofilter = filters.user(list(SUPER_SUDOER_IDS))


def apply_sudo_overrides(overrides: dict[int, bool]) -> set[int]:
    effective = set(CONFIGURED_SUDOERS | SUPER_SUDOER_IDS)
    for user_id, enabled in overrides.items():
        if enabled:
            effective.add(user_id)
        elif user_id not in SUPER_SUDOER_IDS:
            effective.discard(user_id)

    sudofilter.clear()
    sudofilter.update(effective)
    return effective


def is_sudoer(user_id: int | None) -> bool:
    return bool(user_id and user_id in sudofilter)


def is_super_sudoer(user_id: int | None) -> bool:
    return bool(user_id and user_id in SUPER_SUDOER_IDS)


def get_sudoer_ids() -> set[int]:
    return set(sudofilter)
