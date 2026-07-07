# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

import logging
import pkgutil
import time
from importlib import import_module

import hydrogram
from hydrogram import Client
from hydrogram.enums import ParseMode
from hydrogram.errors import BadRequest
from hydrogram.raw.all import layer

from config import API_HASH, API_ID, DISABLED_PLUGINS, LOG_CHAT, TOKEN, WORKERS
from eduu.utils import commands, http

from . import __commit__, __version_number__

logger = logging.getLogger(__name__)

NATIVE_COMMAND_LIMIT = 95
DEFAULT_COMMAND_CATEGORIES = ("general", "tools", "ai")
GROUP_COMMAND_CATEGORIES = (
    "general",
    "tools",
    "ai",
    "mentions",
    "admin_antispam",
    "admin_autoreply",
    "admin_bans",
    "admin_filters",
    "admin_misc",
    "admin_mutes",
    "admin_notes",
    "admin_pins",
    "admin_rules",
    "admin_warns",
    "admin_welcome",
    "remote_moderation",
)
ADMIN_COMMAND_CATEGORIES = (
    "admin_antispam",
    "admin_autoreply",
    "admin_bans",
    "admin_filters",
    "admin_misc",
    "admin_mutes",
    "admin_notes",
    "admin_pins",
    "admin_rules",
    "admin_warns",
    "admin_welcome",
    "mentions",
    "remote_moderation",
)


def _load_command_modules() -> None:
    """Ensure plugin module-level commands.add_command calls have run."""
    from eduu import plugins as plugins_pkg  # noqa: PLC0415

    disabled = {plugin.split()[0].replace("/", ".") for plugin in DISABLED_PLUGINS}
    prefix = f"{plugins_pkg.__name__}."
    for module in pkgutil.walk_packages(plugins_pkg.__path__, prefix):
        module_name = module.name
        short_name = module_name.removeprefix(prefix)
        if short_name in disabled or short_name.split(".", 1)[0] in disabled:
            continue
        try:
            import_module(module_name)
        except Exception as e:
            logger.warning("Skipping command registration import for %s: %s", module_name, e)


async def _set_native_command_menu(scope_commands) -> None:
    registered_counts = {}
    if not scope_commands:
        logger.warning("No Telegram bot menu commands were collected; keeping existing menu.")
        return

    default_commands = scope_commands.get("default", [])
    if not default_commands:
        default_commands = next(
            (commands for commands in scope_commands.values() if commands),
            [],
        )

    scopes = [
        ("default", None, default_commands),
        (
            "all_private_chats",
            {"type": "all_private_chats"},
            scope_commands.get("private", default_commands),
        ),
        (
            "all_group_chats",
            {"type": "all_group_chats"},
            scope_commands.get("group", default_commands),
        ),
        (
            "all_chat_administrators",
            {"type": "all_chat_administrators"},
            scope_commands.get("admin", scope_commands.get("group", default_commands)),
        ),
    ]

    for scope_name, scope, bot_commands in scopes:
        bot_commands = bot_commands[:NATIVE_COMMAND_LIMIT]
        if not bot_commands:
            continue

        command_payload = [
            {"command": command.command, "description": command.description}
            for command in bot_commands
        ]
        payload = {"commands": command_payload}
        if scope is not None:
            payload["scope"] = scope
        response = await http.post(
            f"https://api.telegram.org/bot{TOKEN}/setMyCommands",
            json=payload,
        )
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(
                f"{scope_name}: {data.get('description', 'setMyCommands failed')}"
            )
        registered_counts[scope_name] = len(command_payload)

    logger.info(
        "Registered Telegram bot menu commands: %s.",
        ", ".join(f"{scope}={count}" for scope, count in registered_counts.items()),
    )


class Eduu(Client):
    def __init__(self):
        name = "family_bot"

        super().__init__(
            name=name,
            app_version=f"EduuRobot r{__version_number__} ({__commit__})",
            api_id=API_ID,
            api_hash=API_HASH,
            bot_token=TOKEN,
            parse_mode=ParseMode.HTML,
            workers=WORKERS,
            plugins={"root": "eduu.plugins", "exclude": DISABLED_PLUGINS},
            sleep_threshold=180,
            
        )

    async def start(self):
        await super().start()

        self.start_time = time.time()

        logger.info(
            "Eduu running with Hydrogram v%s (Layer %s) started on @%s. Hi!",
            hydrogram.__version__,
            layer,
            self.me.username,
        )

        try:
            from eduu.utils.localization import default_language, get_locale_string  # noqa: PLC0415

            _load_command_modules()

            def localize(key: str) -> str:
                return get_locale_string(default_language, key)

            await _set_native_command_menu({
                "default": commands.get_bot_commands(
                    localize,
                    categories=DEFAULT_COMMAND_CATEGORIES,
                    limit=NATIVE_COMMAND_LIMIT,
                ),
                "private": commands.get_bot_commands(
                    localize,
                    categories=DEFAULT_COMMAND_CATEGORIES,
                    limit=NATIVE_COMMAND_LIMIT,
                ),
                "group": commands.get_bot_commands(
                    localize,
                    categories=GROUP_COMMAND_CATEGORIES,
                    limit=NATIVE_COMMAND_LIMIT,
                ),
                "admin": commands.get_bot_commands(
                    localize,
                    categories=ADMIN_COMMAND_CATEGORIES,
                    limit=NATIVE_COMMAND_LIMIT,
                ),
            })
        except Exception:
            logger.exception("Unable to register Telegram bot commands.")

        from .database.restarted import del_restarted, get_restarted  # noqa: PLC0415

        wr = await get_restarted()
        await del_restarted()

        start_message = (
            "<b>EduuRobot started!</b>\n\n"
            f"<b>Version number:</b> <code>r{__version_number__} ({__commit__})</code>\n"
            f"<b>Hydrogram:</b> <code>v{hydrogram.__version__}</code>"
        )
        

        try:
            await self.send_message(chat_id=LOG_CHAT, text=start_message)
            if wr:
                await self.edit_message_text(wr[0], wr[1], text="Restarted successfully!")
        except BadRequest:
            logger.warning("Unable to send message to LOG_CHAT.")

    async def stop(self):
        await super().stop()
        logger.warning("Eduu stopped. Bye!")
