#!/usr/bin/env python3
"""Migrate old per-chat autoreply data into the new global autoreply store.

The new bot reads autoreply data from chat_id 0 only. This script copies data
from an old SQLite database into that global target row.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any

GLOBAL_AUTOREPLY_ID = 0

DEFAULT_SETTINGS = {
    "enabled": 1,
    "mode": "random",
    "reply_chance": 50,
    "cooldown_seconds": 10,
    "rate_limit_per_minute": 0,
    "reactions_enabled": 1,
    "reaction_chance": 25,
}


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return bool(row)


def columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def ensure_target_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS autoreply_settings(
            chat_id INTEGER PRIMARY KEY,
            enabled INTEGER DEFAULT 1,
            mode TEXT DEFAULT 'random',
            reply_chance INTEGER DEFAULT 50,
            cooldown_seconds INTEGER DEFAULT 10,
            rate_limit_per_minute INTEGER DEFAULT 0,
            reactions_enabled INTEGER DEFAULT 1,
            reaction_chance INTEGER DEFAULT 25
        );

        CREATE TABLE IF NOT EXISTS autoreply_responses(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            mode TEXT NOT NULL DEFAULT 'random',
            keywords TEXT,
            response_type TEXT NOT NULL,
            text TEXT,
            source_chat_id INTEGER,
            source_message_id INTEGER,
            label TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS autoreply_reactions(
            chat_id INTEGER NOT NULL,
            reaction TEXT NOT NULL,
            UNIQUE(chat_id, reaction)
        );

        CREATE TABLE IF NOT EXISTS autoreply_keyword_reactions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER NOT NULL,
            keywords TEXT NOT NULL,
            reaction TEXT NOT NULL
        );
        """
    )


def source_filter(table_cols: set[str], chat_ids: list[int]) -> tuple[str, list[Any]]:
    if not chat_ids or "chat_id" not in table_cols:
        return "", []
    placeholders = ", ".join("?" for _ in chat_ids)
    return f" WHERE chat_id IN ({placeholders})", list(chat_ids)


def list_source_chats(source: sqlite3.Connection) -> None:
    if not table_exists(source, "autoreply_responses"):
        raise RuntimeError("Source database has no autoreply_responses table.")
    response_cols = columns(source, "autoreply_responses")
    if "chat_id" not in response_cols:
        count = source.execute("SELECT COUNT(*) FROM autoreply_responses").fetchone()[0]
        print(f"Source responses: {count} rows, no chat_id column.")
        return
    rows = source.execute(
        """
        SELECT chat_id, COUNT(*) AS responses
        FROM autoreply_responses
        GROUP BY chat_id
        ORDER BY responses DESC, chat_id
        """
    ).fetchall()
    if not rows:
        print("No source autoreply responses found.")
        return
    print("Source chats with autoreply responses:")
    for row in rows:
        print(f"  {row['chat_id']}: {row['responses']} responses")


def row_value(row: sqlite3.Row | None, key: str, default: Any) -> Any:
    if row is None or key not in row.keys():
        return default
    value = row[key]
    return default if value is None else value


def pick_settings_row(
    source: sqlite3.Connection,
    chat_ids: list[int],
) -> sqlite3.Row | None:
    if not table_exists(source, "autoreply_settings"):
        return None
    settings_cols = columns(source, "autoreply_settings")
    where, params = source_filter(settings_cols, chat_ids)
    query = "SELECT * FROM autoreply_settings" + where
    if "chat_id" in settings_cols:
        query += " ORDER BY chat_id"
    query += " LIMIT 1"
    return source.execute(query, params).fetchone()


def migrate_settings(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    chat_ids: list[int],
) -> int:
    row = pick_settings_row(source, chat_ids)
    values = {key: row_value(row, key, value) for key, value in DEFAULT_SETTINGS.items()}
    target.execute(
        """
        INSERT OR REPLACE INTO autoreply_settings(
            chat_id, enabled, mode, reply_chance, cooldown_seconds,
            rate_limit_per_minute, reactions_enabled, reaction_chance
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            GLOBAL_AUTOREPLY_ID,
            values["enabled"],
            values["mode"],
            values["reply_chance"],
            values["cooldown_seconds"],
            values["rate_limit_per_minute"],
            values["reactions_enabled"],
            values["reaction_chance"],
        ),
    )
    return 1 if row else 0


def migrate_responses(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    chat_ids: list[int],
) -> int:
    if not table_exists(source, "autoreply_responses"):
        return 0
    response_cols = columns(source, "autoreply_responses")
    where, params = source_filter(response_cols, chat_ids)
    rows = source.execute("SELECT * FROM autoreply_responses" + where, params).fetchall()
    for row in rows:
        target.execute(
            """
            INSERT INTO autoreply_responses(
                chat_id, mode, keywords, response_type, text,
                source_chat_id, source_message_id, label, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                GLOBAL_AUTOREPLY_ID,
                row_value(row, "mode", "random"),
                row_value(row, "keywords", "[]"),
                row_value(row, "response_type", "text"),
                row_value(row, "text", None),
                row_value(row, "source_chat_id", None),
                row_value(row, "source_message_id", None),
                row_value(row, "label", None),
                row_value(row, "created_at", None),
            ),
        )
    return len(rows)


def migrate_reactions(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    chat_ids: list[int],
) -> int:
    if not table_exists(source, "autoreply_reactions"):
        return 0
    reaction_cols = columns(source, "autoreply_reactions")
    where, params = source_filter(reaction_cols, chat_ids)
    rows = source.execute("SELECT * FROM autoreply_reactions" + where, params).fetchall()
    for row in rows:
        target.execute(
            """
            INSERT OR IGNORE INTO autoreply_reactions(chat_id, reaction)
            VALUES (?, ?)
            """,
            (GLOBAL_AUTOREPLY_ID, row_value(row, "reaction", "")),
        )
    return len(rows)


def migrate_keyword_reactions(
    source: sqlite3.Connection,
    target: sqlite3.Connection,
    chat_ids: list[int],
) -> int:
    if not table_exists(source, "autoreply_keyword_reactions"):
        return 0
    reaction_cols = columns(source, "autoreply_keyword_reactions")
    where, params = source_filter(reaction_cols, chat_ids)
    rows = source.execute(
        "SELECT * FROM autoreply_keyword_reactions" + where,
        params,
    ).fetchall()
    for row in rows:
        target.execute(
            """
            INSERT INTO autoreply_keyword_reactions(chat_id, keywords, reaction)
            VALUES (?, ?, ?)
            """,
            (
                GLOBAL_AUTOREPLY_ID,
                row_value(row, "keywords", "[]"),
                row_value(row, "reaction", ""),
            ),
        )
    return len(rows)


def clear_target(target: sqlite3.Connection) -> None:
    target.execute("DELETE FROM autoreply_settings WHERE chat_id = ?", (GLOBAL_AUTOREPLY_ID,))
    target.execute("DELETE FROM autoreply_responses WHERE chat_id = ?", (GLOBAL_AUTOREPLY_ID,))
    target.execute("DELETE FROM autoreply_reactions WHERE chat_id = ?", (GLOBAL_AUTOREPLY_ID,))
    target.execute(
        "DELETE FROM autoreply_keyword_reactions WHERE chat_id = ?",
        (GLOBAL_AUTOREPLY_ID,),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate old autoreply SQLite data into global chat_id 0.",
    )
    parser.add_argument("source_db", type=Path, help="Old autoreply SQLite database.")
    parser.add_argument(
        "target_db",
        type=Path,
        nargs="?",
        default=Path("eduu.db"),
        help="Current bot SQLite database. Defaults to eduu.db.",
    )
    parser.add_argument(
        "--source-chat-id",
        type=int,
        action="append",
        default=[],
        help="Only migrate this old chat id. Can be repeated. Defaults to all.",
    )
    parser.add_argument(
        "--clear-target",
        action="store_true",
        help="Delete current global autoreply data before migrating.",
    )
    parser.add_argument(
        "--list-source-chats",
        action="store_true",
        help="List chat ids found in the source database and exit.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write changes. Without this, the script runs a dry-run.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.source_db.exists():
        print(f"Source database does not exist: {args.source_db}", file=sys.stderr)
        return 2
    if not args.target_db.exists() and not args.list_source_chats:
        print(f"Target database does not exist: {args.target_db}", file=sys.stderr)
        return 2

    source = connect(args.source_db)
    try:
        if args.list_source_chats:
            list_source_chats(source)
            return 0

        target = connect(args.target_db)
        try:
            ensure_target_schema(target)
            if args.clear_target:
                clear_target(target)

            counts = {
                "settings": migrate_settings(source, target, args.source_chat_id),
                "responses": migrate_responses(source, target, args.source_chat_id),
                "reactions": migrate_reactions(source, target, args.source_chat_id),
                "keyword_reactions": migrate_keyword_reactions(
                    source,
                    target,
                    args.source_chat_id,
                ),
            }
            if args.apply:
                target.commit()
                action = "Migrated"
            else:
                target.rollback()
                action = "Dry run"

            chat_filter = ", ".join(map(str, args.source_chat_id)) or "all source chats"
            print(f"{action} from {chat_filter} into global chat_id 0:")
            for key, count in counts.items():
                print(f"  {key}: {count}")
            if not args.apply:
                print("\nNo changes were written. Re-run with --apply to migrate.")
            return 0
        finally:
            target.close()
    finally:
        source.close()


if __name__ == "__main__":
    raise SystemExit(main())
