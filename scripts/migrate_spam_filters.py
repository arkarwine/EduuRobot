#!/usr/bin/env python3
"""Reset spam filters for chats to the current default list."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from config import DATABASE_PATH, SPAM_FILTER_WORDS


def normalize_word(word: str) -> str:
    return " ".join(str(word).casefold().split())


def default_words() -> list[str]:
    cleaned = {normalize_word(word) for word in SPAM_FILTER_WORDS if normalize_word(word)}
    return sorted(cleaned)


def connect_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def migrate(conn: sqlite3.Connection, *, dry_run: bool = False) -> int:
    words = default_words()
    if not words:
        raise ValueError("No spam words configured. Check SPAM_FILTER_WORDS in config.py.")

    chats = conn.execute(
        "SELECT chat_id FROM spam_filter_settings UNION SELECT DISTINCT chat_id FROM spam_filters"
    ).fetchall()
    migrated = 0

    for row in chats:
        chat_id = row["chat_id"]
        if dry_run:
            print(f"[dry-run] chat_id={chat_id}: would replace filters with {len(words)} default words")
            continue

        conn.execute("DELETE FROM spam_filters WHERE chat_id = ?", (chat_id,))
        conn.executemany(
            "INSERT INTO spam_filters(chat_id, word) VALUES (?, ?)",
            [(chat_id, word) for word in words],
        )
        conn.execute(
            "INSERT OR IGNORE INTO spam_filter_settings(chat_id) VALUES (?)",
            (chat_id,),
        )
        migrated += 1

    if not dry_run:
        conn.commit()
        print(f"Migrated {migrated} chat(s) to the current default spam filter list.")
    else:
        print(f"Dry run complete: {len(chats)} chat(s) would be migrated.")

    return migrated


def main() -> None:
    parser = argparse.ArgumentParser(description="Replace old spam filter defaults with the configured list.")
    parser.add_argument("--db", type=Path, default=Path(DATABASE_PATH), help="SQLite database path")
    parser.add_argument("--dry-run", action="store_true", help="Show what would change without modifying the DB")
    args = parser.parse_args()

    conn = connect_db(args.db)
    try:
        migrate(conn, dry_run=args.dry_run)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
