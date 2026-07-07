import asyncio
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeCursor:
    def __init__(self, row=None):
        self.row = row

    async def fetchone(self):
        return self.row

    async def fetchall(self):
        return []


class FakeConn:
    def __init__(self, row=None):
        self.row = row
        self.executed = []

    async def execute(self, sql, params=()):
        self.executed.append((sql, params))
        return FakeCursor(self.row)

    async def commit(self):
        return None


def test_auto_reply_imports_and_uses_default_settings():
    sys.modules.pop("eduu.database.auto_reply", None)
    module = importlib.import_module("eduu.database.auto_reply")
    module.conn = FakeConn(None)

    settings = asyncio.run(module.get_settings())

    assert settings["enabled"] is True
    assert settings["reply_chance"] == 50
    assert settings["cooldown_seconds"] == 10


def test_manager_keyboard_keeps_original_action_labels():
    module = importlib.import_module("eduu.plugins.auto_reply")
    keyboard = module.manager_keyboard(123, {"enabled": True, "reply_chance": 50, "reaction_chance": 25, "cooldown_seconds": 10, "rate_limit_per_minute": 0, "global_replies_enabled": True, "global_reactions_enabled": True, "config_overrides": []})

    labels = {button.text for row in keyboard.inline_keyboard for button in row}

    assert "➕ Add Replies" in labels
    assert "📚 Replies" in labels
    assert "➕ Add Reactions" in labels
    assert "🎭 Reactions" in labels
    assert "🗑 Clear Replies" in labels
