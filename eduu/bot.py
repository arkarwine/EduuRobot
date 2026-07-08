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
from eduu.utils.bot_identity import cache_bot_identity

from . import __commit__, __version_number__

logger = logging.getLogger(__name__)

NATIVE_COMMAND_LIMIT = 20
NATIVE_COMMAND_CATEGORIES = ("general", "tools", "ai")
MAIN_NATIVE_COMMANDS = (
    "start",
    "stats",
    "ping",
    "id",
    "info",
    "admins",
    "rules",
    "weather",
    "tr",
    "tiktok",
    "ai",
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


async def _delete_native_command_menu(scope_name: str, scope: dict | None) -> None:
    payload = {}
    if scope is not None:
        payload["scope"] = scope
    response = await http.post(
        f"https://api.telegram.org/bot{TOKEN}/deleteMyCommands",
        json=payload,
    )
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(
            f"{scope_name}: {data.get('description', 'deleteMyCommands failed')}"
        )


async def _set_native_command_menu(bot_commands) -> None:
    if not bot_commands:
        logger.warning("No Telegram bot menu commands were collected; keeping existing menu.")
        return

    for scope_name, scope in [
        ("default", None),
        ("all_group_chats", {"type": "all_group_chats"}),
        ("all_chat_administrators", {"type": "all_chat_administrators"}),
    ]:
        await _delete_native_command_menu(scope_name, scope)

    bot_commands = bot_commands[:NATIVE_COMMAND_LIMIT]
    command_payload = [
        {"command": command.command, "description": command.description}
        for command in bot_commands
    ]
    response = await http.post(
        f"https://api.telegram.org/bot{TOKEN}/setMyCommands",
        json={
            "scope": {"type": "all_private_chats"},
            "commands": command_payload,
        },
    )
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(
            f"all_private_chats: {data.get('description', 'setMyCommands failed')}"
        )

    logger.info(
        "Registered %s Telegram bot menu commands for private chats only.",
        len(command_payload),
    )


def _main_native_commands(bot_commands):
    by_name = {command.command: command for command in bot_commands}
    return [by_name[name] for name in MAIN_NATIVE_COMMANDS if name in by_name]


class Eduu(Client):
    def __init__(self):
        name = "family_bot"

        super().__init__(
            name=name,
            app_version=f"family_bot r{__version_number__} ({__commit__})",
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
        cache_bot_identity(name=self.me.first_name, username=self.me.username)
        bot_name = self.me.first_name or self.me.username or "Bot"

        logger.info(
            "%s running with Hydrogram v%s (Layer %s) started on @%s. Hi!",
            bot_name,
            hydrogram.__version__,
            layer,
            self.me.username,
        )

        try:
            from eduu.utils.localization import default_language, get_locale_string  # noqa: PLC0415

            _load_command_modules()

            def localize(key: str) -> str:
                return get_locale_string(default_language, key)

            native_commands = commands.get_bot_commands(
                localize,
                categories=NATIVE_COMMAND_CATEGORIES,
                limit=100,
            )
            await _set_native_command_menu(_main_native_commands(native_commands))
        except Exception:
            logger.exception("Unable to register Telegram bot commands.")

        from .database.restarted import del_restarted, get_restarted  # noqa: PLC0415

        wr = await get_restarted()
        await del_restarted()

        start_message = (
            f"<b>{bot_name} started!</b>\n\n"
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
