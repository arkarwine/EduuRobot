#!/usr/bin/env python3
"""Repost global autoreply source messages and update their SQLite references."""

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import API_HASH, API_ID, DATABASE_PATH  # noqa: E402
from hydrogram import Client  # noqa: E402

GLOBAL_AUTOREPLY_ID = 0
SESSION_NAME = "autoreply_migration_user"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Copy distinct global autoreply source messages into a chat accessible "
            "to the bot, then update their SQLite references."
        )
    )
    parser.add_argument(
        "--database",
        type=Path,
        default=Path(DATABASE_PATH),
        help="Bot SQLite database (defaults to config.DATABASE_PATH).",
    )
    parser.add_argument(
        "--target-chat-id",
        required=True,
        type=int,
        help="Chat ID where the user account will repost the messages.",
    )
    parser.add_argument(
        "--source-chat-id",
        type=int,
        help="Only process source messages from this chat ID.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Process at most this many distinct source messages (useful for a trial).",
    )
    parser.add_argument(
        "--mapping-file",
        type=Path,
        help="Resume mapping file; defaults to <database>.autoreply-message-map.json.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually fetch, repost, and update the database. Without this, list counts only.",
    )
    return parser.parse_args()


def source_rows(
    conn: sqlite3.Connection,
    source_chat_id: int | None,
    limit: int | None,
) -> list[tuple[int, int, int]]:
    query = """
        SELECT source_chat_id, source_message_id, COUNT(*)
        FROM autoreply_responses
        WHERE chat_id = ?
          AND response_type = 'message'
          AND source_chat_id IS NOT NULL
          AND source_message_id IS NOT NULL
    """
    params: list[int] = [GLOBAL_AUTOREPLY_ID]
    if source_chat_id is not None:
        query += " AND source_chat_id = ?"
        params.append(source_chat_id)
    query += (
        " GROUP BY source_chat_id, source_message_id "
        "ORDER BY source_chat_id, source_message_id"
    )
    rows = [
        (int(chat), int(message), int(count))
        for chat, message, count in conn.execute(query, params)
    ]
    if limit is not None:
        rows = rows[:limit]
    return rows


def load_mapping(path: Path, target_chat_id: int) -> dict[str, int]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("target_chat_id") != target_chat_id:
        raise ValueError(
            f"Mapping file target {data.get('target_chat_id')} does not match "
            f"--target-chat-id {target_chat_id}"
        )
    mappings = data.get("messages")
    if not isinstance(mappings, dict):
        raise ValueError(f"Invalid mapping file: {path}")
    return {str(key): int(value) for key, value in mappings.items()}


def save_mapping(path: Path, target_chat_id: int, mappings: dict[str, int]) -> None:
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(
            {"target_chat_id": target_chat_id, "messages": mappings},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def create_backup(conn: sqlite3.Connection, database: Path) -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup_path = database.with_name(f"{database.name}.backup-{timestamp}")
    with sqlite3.connect(backup_path) as backup:
        conn.backup(backup)
    return backup_path


async def migrate(
    conn: sqlite3.Connection,
    database: Path,
    rows: list[tuple[int, int, int]],
    target_chat_id: int,
    mapping_path: Path,
    session_string: str,
) -> None:
    if API_ID <= 0 or not API_HASH or API_HASH.startswith("YOUR_"):
        raise ValueError("Set valid API_ID and API_HASH in config.py or .env first.")
    if not session_string:
        raise ValueError("A Hydrogram user session string is required.")

    mappings = load_mapping(mapping_path, target_chat_id)
    mapping_path.parent.mkdir(parents=True, exist_ok=True)
    completed_targets = {(target_chat_id, new_id) for new_id in mappings.values()}
    already_updated = [
        row for row in rows if (row[0], row[1]) in completed_targets
    ]
    rows_with_mapping = [
        row for row in rows if f"{row[0]}:{row[1]}" in mappings
    ]
    pending = [
        row
        for row in rows
        if f"{row[0]}:{row[1]}" not in mappings
        and (row[0], row[1]) not in completed_targets
    ]

    if not rows_with_mapping and not pending:
        print("All selected autoreply references already point to mapped target messages.")
        return

    client = Client(
        SESSION_NAME,
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=session_string,
        workdir=str(ROOT / "eduu"),
        no_updates=True,
    )
    started = False
    try:
        await client.start()
        started = True

        fetched = []
        unavailable = []
        for source_chat, source_message, count in pending:
            message = await client.get_messages(source_chat, source_message)
            if not message or message.empty:
                unavailable.append((source_chat, source_message))
            else:
                fetched.append((source_chat, source_message, count, message))

        if unavailable:
            ids = ", ".join(f"{chat}/{message}" for chat, message in unavailable[:20])
            raise RuntimeError(
                f"{len(unavailable)} source messages are missing or inaccessible "
                f"(first IDs: {ids}). No messages were reposted."
            )

        backup_path = create_backup(conn, database)
        print(f"Database backup created: {backup_path}")

        for source_chat, source_message, _, message in fetched:
            copied = await message.copy(target_chat_id)
            if not copied or copied.empty:
                raise RuntimeError(
                    f"Hydrogram did not return the copied message for "
                    f"{source_chat}/{source_message}; database was not updated."
                )
            mappings[f"{source_chat}:{source_message}"] = copied.id
            save_mapping(mapping_path, target_chat_id, mappings)
            print(f"Copied {source_chat}/{source_message} -> {target_chat_id}/{copied.id}")

        rows_to_update = [
            row
            for row in rows
            if f"{row[0]}:{row[1]}" in mappings
            and (row[0], row[1]) not in completed_targets
        ]
        conn.execute("BEGIN IMMEDIATE")
        updated = sum(count for _, _, count in already_updated)
        for source_chat, source_message, expected_count in rows_to_update:
            new_message = mappings.get(f"{source_chat}:{source_message}")
            if new_message is None:
                raise RuntimeError(
                    f"Mapping missing for source {source_chat}/{source_message}."
                )
            cursor = conn.execute(
                """
                UPDATE autoreply_responses
                SET source_chat_id = ?, source_message_id = ?
                WHERE chat_id = ?
                  AND response_type = 'message'
                  AND source_chat_id = ?
                  AND source_message_id = ?
                """,
                (
                    target_chat_id,
                    new_message,
                    GLOBAL_AUTOREPLY_ID,
                    source_chat,
                    source_message,
                ),
            )
            if cursor.rowcount != expected_count:
                raise RuntimeError(
                    f"Expected to update {expected_count} rows for "
                    f"{source_chat}/{source_message}, updated {cursor.rowcount}. "
                    "Database transaction will be rolled back."
                )
            updated += cursor.rowcount
        conn.commit()
        print(
            f"Updated {updated} autoreply rows using {len(rows)} selected source messages. "
            f"Resume mapping: {mapping_path}"
        )
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    finally:
        if started:
            await client.stop()


def main() -> int:
    args = parse_args()
    if args.limit is not None and args.limit < 1:
        raise SystemExit("--limit must be a positive integer.")
    database = args.database.expanduser().resolve()
    if not database.is_file():
        raise SystemExit(f"Database does not exist: {database}")
    mapping_path = (
        args.mapping_file.expanduser().resolve()
        if args.mapping_file
        else database.with_name(database.name + ".autoreply-message-map.json")
    )

    conn = sqlite3.connect(database)
    try:
        rows = source_rows(conn, args.source_chat_id, args.limit)
        if not rows:
            raise SystemExit("No matching global message-based autoreplies were found.")
        print(
            f"Selected {len(rows)} distinct source messages referenced by "
            f"{sum(row[2] for row in rows)} autoreply rows."
        )
        if not args.apply:
            print("Dry run only. Add --apply to log in and repost the messages.")
            return 0
        session_string = getpass.getpass("Hydrogram user session string: ").strip()
        if not session_string:
            raise SystemExit("A non-empty Hydrogram session string is required.")
        asyncio.run(
            migrate(
                conn,
                database,
                rows,
                args.target_chat_id,
                mapping_path,
                session_string,
            )
        )
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
