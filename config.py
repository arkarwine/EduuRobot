from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import List


def _load_dotenv(path: str = ".env") -> None:
    env_path = Path(path)
    if not env_path.is_absolute():
        env_path = Path(__file__).resolve().with_name(path)
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


def _env_str(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return int(value)


def _env_list(name: str, default: list) -> list:
    value = os.environ.get(name)
    if value is None or value == "":
        return list(default)
    try:
        parsed = ast.literal_eval(value)
        if isinstance(parsed, (list, tuple, set)):
            return list(parsed)
    except (SyntaxError, ValueError):
        pass
    return [item.strip() for item in value.split(",") if item.strip()]


def _env_int_list(name: str, default: list[int]) -> list[int]:
    return [int(item) for item in _env_list(name, default)]


_load_dotenv()

# This is a template configuration file for EduuRobot.
# You can use this file as a base for your own config file by
# copying this file to `config.py` and filling in the values.
#


# API keys

# Bot token from Bot Father
TOKEN: str = _env_str("TOKEN", "123123:YOUR_BOT_TOKEN_HERE")

# Telegram API ID and API hash
# Get it from https://my.telegram.org/apps
API_ID: int = _env_int("API_ID", 321321)
API_HASH: str = _env_str("API_HASH", "YOUR_API_HASH_HERE")

# Tenor API key
# Get it from https://tenor.com/developer/keyregistration
# Can be empty (but the /gif command won't work without it)
TENOR_API_KEY: str = _env_str("TENOR_API_KEY", "")

# Google Gemini API key
# Get it from https://aistudio.google.com/app/apikey
# Can be empty (but the /ai command won't work without it)
GEMINI_API_KEY: str = _env_str("GEMINI_API_KEY", "")


# Admins/sudoers settings

# Sudoers and super sudoers
SUPER_SUDOERS: List[int] = _env_int_list("SUPER_SUDOERS", [123456789])
SUDOERS: List[int] = _env_int_list("SUDOERS", [987654321])

# All super sudoers should be sudoers as well
SUDOERS.extend(SUPER_SUDOERS)


# Other settings

# Database file path
DATABASE_PATH = _env_str("DATABASE_PATH", "eduu.db")

# Default moderation action to apply after a user reaches the warning limit
# Supported values: mute, ban, kick
DEFAULT_WARN_ACTION: str = _env_str("DEFAULT_WARN_ACTION", "mute").strip().lower()
if DEFAULT_WARN_ACTION not in {"mute", "ban", "kick"}:
    DEFAULT_WARN_ACTION = "mute"

# Duration in days of the default mute applied after reaching the warning limit
WARNING_MUTE_DAYS: float = _env_int("WARNING_MUTE_DAYS", 7)

# Duration in hours of the mute applied for profanity warnings after the 3-strike threshold
PROFANITY_MUTE_HOURS: int = _env_int("PROFANITY_MUTE_HOURS", 2)

# Number of updates that can be processed in parallel
WORKERS = _env_int("WORKERS", 24)

# Chat used for logging
LOG_CHAT: int = _env_int("LOG_CHAT", 123456789)

# Prefixes for commands
# e.g: /command and !command
PREFIXES: List[str] = _env_list("PREFIXES", ["/", "!"])

# Updates channel username (e.g., "@channelname" or full URL)
UPDATES_CHANNEL: str = _env_str("UPDATES_CHANNEL", "")

# Owner username or URL (e.g., "@username" or full URL)
OWNER_URL: str = _env_str("OWNER_URL", "")

# Support group username or URL (e.g., "@groupname" or full URL)
SUPPORT_GROUP: str = _env_str("SUPPORT_GROUP", "")

# Image URL to show on /start in private chats
START_IMG_URL: str = _env_str("START_IMG_URL", "")

# Default exact words treated as spam when anti-spam is enabled.
# These are used by the existing warning-based anti-spam flow.
DEFAULT_PROFANITY_WORDS: List[str] = [
    "လီး",
    "စောက်ပတ်",
    "လိုး",
    "စောက်",
    "စောက်ဖုတ်",
    "ဖာ",
    "ဖာသည်",
    "စောက်ခွက်",
    "စောက်ကောင်",
    "စောက်ရူး",
    "စောက်ပေါ",
    "စောက်တုံး",
    "စောက်ညံ့",
    "စောက်နုံ",
    "စောက်ကြောင်",
    "စောက်ရှက်",
    "စောက်ကျိုးနည်း",
    "စောက်သုံးမကျ",
    "စောက်တလွဲ",
    "စောက်ပျင်း",
    "စောက်ထင်",
    "စောက်ဆင့်",
    "စောက်ခွက်ပျက်",
    "စောက်မျက်နှာ",
    "စောက်မျက်နှာပေါ",
    "စောက်အူ",
    "စောက်သိက္ခာ",
    "စောက်ရမ်း",
    "စောက်ကလေး",
    "စောက်ကောင်မ",
    "စောက်မ",
    "စောက်မိန်းမ",
    "စောက်မသား",
    "စောက်သား",
    "စောက်သားမ",
    "စောက်ဖုတ်ကြီး",
    "စောက်ပတ်ကြီး",
    "စောက်ပတ်ပျက်",
    "စောက်ဖုတ်ပျက်",
    "စောက်ဖုတ်စား",
    "လီးစား",
    "လီးပဲ",
    "လီးကောင်",
    "လီးကောင်မ",
    "လီးစုပ်",
    "လီးစုပ်မ",
    "လီးစုပ်ကောင်",
    "လီးစုပ်ခွေး",
    "လီးလိုး",
    "လီးလိုးကောင်",
    "လီးလိုးမ",
    "လိုးကောင်",
    "လိုးမ",
    "လိုးခွေး",
    "လိုးဖို့",
    "လိုးနေ",
    "လိုးစား",
    "လိုးကောင်မ",
    "အမေလိုး",
    "အမေလိုးကောင်",
    "အမေလိုးမ",
    "အမေလိုးသား",
    "အမေလိုးခွေး",
    "မအေလိုး",
    "မအေလိုးကောင်",
    "မအေလိုးမ",
    "မအေလိုးသား",
    "မအေလိုးခွေး",
    "အဖေလိုး",
    "အဖေလိုးကောင်",
    "အဖေလိုးမ",
    "အဖေလိုးသား",
    "မိဘလိုး",
    "မိဘလိုးကောင်",
    "သားအမေလိုး",
    "သမီးအမေလိုး",
    "မင်းအမေလိုး",
    "မင်းအဖေလိုး",
    "မင်းမအေလိုး",
    "ငါ့အမေလိုး",
    "ငါ့အဖေလိုး",
    "ခွေးသား",
    "ခွေးမ",
    "ခွေးမသား",
    "ခွေးမသားလိုး",
    "ခွေးလိုး",
    "ခွေးလိုးကောင်",
    "ခွေးလိုးမ",
    "ခွေးစုတ်",
    "ခွေးစုတ်ကောင်",
    "ခွေးစုတ်မ",
    "ခွေးသူတောင်းစား",
    "ဖာခေါင်း",
    "ဖာသည်မ",
    "ဖာသည်သား",
    "ဖာသည်ကောင်",
    "ဖာသည်မသား",
    "ဖာခေါင်းမ",
    "အပြာမ",
    "အပြာကောင်",
    "အပြာစား",
    "ကာမစိတ်",
    "လိင်ဆက်ဆံ",
    "လိင်အင်္ဂါ",
    "လီးကြီး",
    "လီးသေး",
    "လီးရှည်",
    "လီးတို",
]
SPAM_FILTER_WORDS: List[str] = _env_list("SPAM_FILTER_WORDS", DEFAULT_PROFANITY_WORDS)

# List of disabled plugins
# Example: DISABLED_PLUGINS=ai,autoreply,tiktok
DISABLED_PLUGINS: List[str] = _env_list("DISABLED_PLUGINS", [])

if not GEMINI_API_KEY:
    DISABLED_PLUGINS.append("ai")
