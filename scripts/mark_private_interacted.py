#!/usr/bin/env python3
"""Mark logged private chats as private_interacted for broadcast eligibility."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

PRIVATE_TYPES = ("ChatType.PRIVATE", "private")


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_private_interacted_column(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(chat_logs)")}
    if "private_interacted" not in columns:
        conn.execute("ALTER TABLE chat_logs ADD COLUMN private_interacted INTEGER DEFAULT 0")


def count_private_rows(conn: sqlite3.Connection) -> tuple[int, int]:
    total = conn.execute(
        "SELECT COUNT(*) FROM chat_logs WHERE chat_type IN (?, ?)",
        PRIVATE_TYPES,
    ).fetchone()[0]
    pending = conn.execute(
        """
        SELECT COUNT(*)
        FROM chat_logs
        WHERE chat_type IN (?, ?)
          AND COALESCE(private_interacted, 0) = 0
        """,
        PRIVATE_TYPES,
    ).fetchone()[0]
    return int(total), int(pending)


def mark_private_rows(conn: sqlite3.Connection) -> int:
    cursor = conn.execute(
        """
        UPDATE chat_logs
        SET private_interacted = 1,
            last_seen = CURRENT_TIMESTAMP
        WHERE chat_type IN (?, ?)
          AND COALESCE(private_interacted, 0) = 0
        """,
        PRIVATE_TYPES,
    )
    return int(cursor.rowcount)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Set private_interacted=1 for all private rows in chat_logs.",
    )
    parser.add_argument(
        "database",
        type=Path,
        nargs="?",
        default=Path("eduu.db"),
        help="SQLite database path. Defaults to eduu.db.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write changes. Without this, only prints what would change.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.database.exists():
        print(f"Database does not exist: {args.database}")
        return 2

    conn = connect(args.database)
    try:
        ensure_private_interacted_column(conn)
        total, pending = count_private_rows(conn)
        changed = mark_private_rows(conn)
        if args.apply:
            conn.commit()
            action = "Updated"
        else:
            conn.rollback()
            action = "Dry run"

        print(f"{action}: {args.database}")
        print(f"Private chat rows: {total}")
        print(f"Rows needing private_interacted=1: {pending}")
        print(f"Rows changed: {changed}")
        if not args.apply:
            print("No changes were written. Re-run with --apply to update the database.")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
