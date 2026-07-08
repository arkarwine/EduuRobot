#!/usr/bin/env python3
"""Migrate old MongoDB autoreply data into this bot's SQLite store.

The old AutoReply bot stored data in MongoDB collections:
  - groups
  - bot_settings
  - users

The new bot reads autoreply data from SQLite rows with chat_id 0 only.
Broadcast targets are read from SQLite chat_logs, so this script can also
seed chat_logs from old MongoDB groups/users.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

GLOBAL_AUTOREPLY_ID = 0
DEFAULT_REACTIONS = ["👍", "❤️", "😂", "🎉", "👀"]
DEFAULT_SETTINGS = {
    "enabled": True,
    "reply_mode": "random",
    "reply_chance": 50,
    "cooldown_seconds": 10,
    "rate_limit_per_minute": 0,
    "reactions_enabled": True,
    "reaction_chance": 25,
    "reactions": list(DEFAULT_REACTIONS),
}


def import_mongo_client():
    try:
        from pymongo import MongoClient
    except ImportError:
        print(
            "pymongo is required for Mongo migration. Install it with: pip install pymongo",
            file=sys.stderr,
        )
        raise
    return MongoClient


def connect_sqlite(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def connect_mongo(uri: str):
    mongo_client = import_mongo_client()
    client = mongo_client(uri, serverSelectionTimeoutMS=5000)
    client.admin.command("ping")
    return client


def ensure_target_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS groups(
            chat_id INTEGER PRIMARY KEY,
            welcome TEXT,
            welcome_enabled INTEGER,
            goodbye TEXT,
            goodbye_enabled INTEGER,
            rules TEXT,
            warns_limit INTEGER,
            chat_lang TEXT,
            cached_admins,
            antichannelpin INTEGER,
            delservicemsgs INTEGER,
            antispam INTEGER DEFAULT 1,
            warn_action TEXT,
            tiktok_autodl INTEGER DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            chat_lang TEXT
        );

        CREATE TABLE IF NOT EXISTS channels(
            chat_id INTEGER PRIMARY KEY,
            chat_lang TEXT
        );

        CREATE TABLE IF NOT EXISTS chat_logs(
            chat_id INTEGER PRIMARY KEY,
            chat_type TEXT,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            chat_title TEXT,
            private_interacted INTEGER DEFAULT 0
        );

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
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(chat_logs)")}
    if "private_interacted" not in columns:
        conn.execute("ALTER TABLE chat_logs ADD COLUMN private_interacted INTEGER DEFAULT 0")


def clear_autoreply_target(target: sqlite3.Connection) -> None:
    target.execute("DELETE FROM autoreply_settings WHERE chat_id = ?", (GLOBAL_AUTOREPLY_ID,))
    target.execute("DELETE FROM autoreply_responses WHERE chat_id = ?", (GLOBAL_AUTOREPLY_ID,))
    target.execute("DELETE FROM autoreply_reactions WHERE chat_id = ?", (GLOBAL_AUTOREPLY_ID,))
    target.execute(
        "DELETE FROM autoreply_keyword_reactions WHERE chat_id = ?",
        (GLOBAL_AUTOREPLY_ID,),
    )


def clear_chat_logs_target(target: sqlite3.Connection) -> None:
    target.execute("DELETE FROM chat_logs")


def normalize_keywords(keywords: Iterable[Any]) -> list[str]:
    normalized = []
    for keyword in keywords:
        value = " ".join(str(keyword).casefold().strip().split())
        if value and value not in normalized:
            normalized.append(value)
    return normalized


def safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def preview(value: Any, limit: int = 80) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = " ".join(value.split())
    elif isinstance(value, dict):
        text = (
            value.get("label")
            or value.get("text")
            or value.get("caption")
            or value.get("description")
            or safe_json(value)
        )
        text = " ".join(str(text).split())
    else:
        text = " ".join(str(value).split())
    return text[: limit - 3] + "..." if len(text) > limit else text


def first_value(data: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data and data[key] is not None:
            return data[key]
    return None


def int_id(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def document_id(document: dict[str, Any]) -> int | None:
    return int_id(first_value(document, "_id", "id", "chat_id", "user_id"))


def chat_title(document: dict[str, Any], fallback: str) -> str:
    value = first_value(
        document,
        "title",
        "chat_title",
        "name",
        "first_name",
        "username",
    )
    if value is None:
        return fallback
    return str(value)


def response_to_row(
    response: Any,
    *,
    mode: str,
    keywords: list[str] | None = None,
) -> dict[str, Any]:
    if isinstance(response, str):
        return {
            "mode": mode,
            "keywords": keywords or [],
            "response_type": "text",
            "text": response,
            "source_chat_id": None,
            "source_message_id": None,
            "label": preview(response),
        }

    if isinstance(response, dict):
        source_chat_id = first_value(
            response,
            "source_chat_id",
            "chat_id",
            "from_chat_id",
        )
        source_message_id = first_value(
            response,
            "source_message_id",
            "message_id",
            "id",
        )
        text = first_value(response, "text", "caption")
        if source_chat_id is not None and source_message_id is not None:
            return {
                "mode": mode,
                "keywords": keywords or [],
                "response_type": "message",
                "text": text,
                "source_chat_id": int(source_chat_id),
                "source_message_id": int(source_message_id),
                "label": preview(response),
            }
        if text:
            return {
                "mode": mode,
                "keywords": keywords or [],
                "response_type": "text",
                "text": str(text),
                "source_chat_id": None,
                "source_message_id": None,
                "label": preview(response),
            }

    dumped = safe_json(response)
    return {
        "mode": mode,
        "keywords": keywords or [],
        "response_type": "text",
        "text": dumped,
        "source_chat_id": None,
        "source_message_id": None,
        "label": preview(dumped),
    }


def insert_response(target: sqlite3.Connection, row: dict[str, Any]) -> None:
    target.execute(
        """
        INSERT INTO autoreply_responses(
            chat_id, mode, keywords, response_type, text,
            source_chat_id, source_message_id, label
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            GLOBAL_AUTOREPLY_ID,
            row["mode"],
            safe_json(row["keywords"]),
            row["response_type"],
            row["text"],
            row["source_chat_id"],
            row["source_message_id"],
            row["label"],
        ),
    )


def insert_reaction(target: sqlite3.Connection, reaction: Any) -> bool:
    reaction = str(reaction).strip()
    if not reaction:
        return False
    cursor = target.execute(
        """
        INSERT OR IGNORE INTO autoreply_reactions(chat_id, reaction)
        VALUES (?, ?)
        """,
        (GLOBAL_AUTOREPLY_ID, reaction),
    )
    return cursor.rowcount > 0


def insert_keyword_reaction(
    target: sqlite3.Connection,
    keywords: list[str],
    reaction: Any,
) -> bool:
    reaction = str(reaction).strip()
    keywords = normalize_keywords(keywords)
    if not keywords or not reaction:
        return False
    target.execute(
        """
        INSERT INTO autoreply_keyword_reactions(chat_id, keywords, reaction)
        VALUES (?, ?, ?)
        """,
        (GLOBAL_AUTOREPLY_ID, safe_json(keywords), reaction),
    )
    return True


def global_config(db) -> dict[str, Any]:
    document = db["bot_settings"].find_one({"_id": "global_config"}) or {}
    return DEFAULT_SETTINGS | document


def migrate_settings(db, target: sqlite3.Connection) -> int:
    config = global_config(db)
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
            int(bool(config.get("enabled", True))),
            config.get("reply_mode", "random"),
            int(config.get("reply_chance", 50)),
            int(config.get("cooldown_seconds", 10)),
            int(config.get("rate_limit_per_minute", 0)),
            int(bool(config.get("reactions_enabled", True))),
            int(config.get("reaction_chance", 25)),
        ),
    )
    return 1


def migrate_global_data(db, target: sqlite3.Connection) -> dict[str, int]:
    counts = {
        "global_responses": 0,
        "global_keyword_responses": 0,
        "global_reactions": 0,
        "global_keyword_reactions": 0,
    }

    responses_doc = db["bot_settings"].find_one({"_id": "global_responses"}) or {}
    for response in responses_doc.get("responses", []):
        insert_response(target, response_to_row(response, mode="random"))
        counts["global_responses"] += 1

    keyword_doc = db["bot_settings"].find_one({"_id": "global_keyword_responses"}) or {}
    for entry in keyword_doc.get("responses", []):
        keywords = normalize_keywords(entry.get("keywords", []))
        insert_response(
            target,
            response_to_row(entry.get("response"), mode="keyword", keywords=keywords),
        )
        counts["global_keyword_responses"] += 1

    for reaction in global_config(db).get("reactions", DEFAULT_REACTIONS):
        if insert_reaction(target, reaction):
            counts["global_reactions"] += 1

    keyword_reactions_doc = (
        db["bot_settings"].find_one({"_id": "global_keyword_reactions"}) or {}
    )
    for entry in keyword_reactions_doc.get("reactions", []):
        if insert_keyword_reaction(
            target,
            entry.get("keywords", []),
            entry.get("reaction", ""),
        ):
            counts["global_keyword_reactions"] += 1

    return counts


def group_query(source_chat_ids: list[int]) -> dict[str, Any]:
    if not source_chat_ids:
        return {}
    return {"_id": {"$in": source_chat_ids}}


def upsert_chat_log(
    target: sqlite3.Connection,
    chat_id: int,
    chat_type: str,
    title: str,
    *,
    private_interacted: bool = False,
) -> bool:
    cursor = target.execute(
        """
        INSERT OR IGNORE INTO chat_logs(chat_id, chat_type, chat_title, private_interacted)
        VALUES (?, ?, ?, ?)
        """,
        (chat_id, chat_type, title, int(private_interacted)),
    )
    inserted = cursor.rowcount > 0
    target.execute(
        """
        UPDATE chat_logs
        SET chat_type = ?,
            chat_title = ?,
            private_interacted = CASE
                WHEN ? = 1 THEN 1
                ELSE private_interacted
            END,
            last_seen = CURRENT_TIMESTAMP
        WHERE chat_id = ?
        """,
        (chat_type, title, int(private_interacted), chat_id),
    )
    return inserted


def ensure_group_row(target: sqlite3.Connection, chat_id: int) -> bool:
    cursor = target.execute(
        """
        INSERT OR IGNORE INTO groups(chat_id, welcome_enabled, antispam, tiktok_autodl)
        VALUES (?, ?, ?, ?)
        """,
        (chat_id, 1, 1, 1),
    )
    return cursor.rowcount > 0


def ensure_user_row(target: sqlite3.Connection, user_id: int) -> bool:
    cursor = target.execute(
        "INSERT OR IGNORE INTO users(user_id) VALUES (?)",
        (user_id,),
    )
    return cursor.rowcount > 0


def migrate_chat_logs(
    db,
    target: sqlite3.Connection,
    source_chat_ids: list[int],
    *,
    include_users: bool,
    include_all_users: bool,
) -> dict[str, int]:
    counts = {
        "broadcast_group_targets": 0,
        "broadcast_user_targets": 0,
        "groups_table_rows": 0,
        "users_table_rows": 0,
        "skipped_group_targets": 0,
        "skipped_user_targets": 0,
    }

    for document in db["groups"].find(group_query(source_chat_ids)):
        chat_id = document_id(document)
        if chat_id is None:
            counts["skipped_group_targets"] += 1
            continue
        title = chat_title(document, str(chat_id))
        if ensure_group_row(target, chat_id):
            counts["groups_table_rows"] += 1
        if upsert_chat_log(target, chat_id, "ChatType.SUPERGROUP", title):
            counts["broadcast_group_targets"] += 1

    if include_users and "users" in db.list_collection_names():
        user_query = {} if include_all_users else {"private_interacted": True}
        for document in db["users"].find(user_query):
            user_id = document_id(document)
            if user_id is None:
                counts["skipped_user_targets"] += 1
                continue
            title = chat_title(document, str(user_id))
            if ensure_user_row(target, user_id):
                counts["users_table_rows"] += 1
            if upsert_chat_log(
                target,
                user_id,
                "ChatType.PRIVATE",
                title,
                private_interacted=bool(document.get("private_interacted")),
            ):
                counts["broadcast_user_targets"] += 1

    return counts


def migrate_group_data(
    db,
    target: sqlite3.Connection,
    source_chat_ids: list[int],
) -> dict[str, int]:
    counts = {
        "group_responses": 0,
        "group_keyword_responses": 0,
        "group_reactions": 0,
        "group_keyword_reactions": 0,
        "groups": 0,
    }
    for document in db["groups"].find(group_query(source_chat_ids)):
        counts["groups"] += 1
        for response in document.get("responses", []):
            insert_response(target, response_to_row(response, mode="random"))
            counts["group_responses"] += 1

        for entry in document.get("keyword_responses", []):
            insert_response(
                target,
                response_to_row(
                    entry.get("response"),
                    mode="keyword",
                    keywords=normalize_keywords(entry.get("keywords", [])),
                ),
            )
            counts["group_keyword_responses"] += 1

        overrides = set(document.get("config_overrides", []))
        if "reactions" in overrides:
            for reaction in document.get("reactions", []):
                if insert_reaction(target, reaction):
                    counts["group_reactions"] += 1

        for entry in document.get("keyword_reactions", []):
            if insert_keyword_reaction(
                target,
                entry.get("keywords", []),
                entry.get("reaction", ""),
            ):
                counts["group_keyword_reactions"] += 1

    return counts


def list_source(db) -> None:
    print("Global data:")
    global_responses = db["bot_settings"].find_one({"_id": "global_responses"}) or {}
    print(
        "  responses:",
        len(global_responses.get("responses", [])),
    )
    print(
        "  keyword responses:",
        len(
            (db["bot_settings"].find_one({"_id": "global_keyword_responses"}) or {}).get(
                "responses",
                [],
            )
        ),
    )
    print(
        "  keyword reactions:",
        len(
            (db["bot_settings"].find_one({"_id": "global_keyword_reactions"}) or {}).get(
                "reactions",
                [],
            )
        ),
    )
    print("\nGroups:")
    cursor = db["groups"].find(
        {},
        {
            "_id": 1,
            "responses": 1,
            "keyword_responses": 1,
            "keyword_reactions": 1,
            "reactions": 1,
            "config_overrides": 1,
        },
    )
    found = False
    for document in cursor:
        found = True
        overrides = set(document.get("config_overrides", []))
        reactions = len(document.get("reactions", [])) if "reactions" in overrides else 0
        print(
            f"  {document['_id']}: "
            f"{len(document.get('responses', []))} responses, "
            f"{len(document.get('keyword_responses', []))} keyword responses, "
            f"{reactions} local reactions, "
            f"{len(document.get('keyword_reactions', []))} keyword reactions"
        )
    if not found:
        print("  none")

    print("\nBroadcast targets:")
    print("  groups:", db["groups"].count_documents({}))
    users_count = db["users"].count_documents({}) if "users" in db.list_collection_names() else 0
    print("  users:", users_count)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate old MongoDB autoreply data into SQLite chat_id 0.",
    )
    parser.add_argument("--mongo-uri", required=True, help="Old MongoDB URI.")
    parser.add_argument("--mongo-db", required=True, help="Old MongoDB database name.")
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
        help="Only migrate this old group id. Can be repeated. Defaults to all groups.",
    )
    parser.add_argument(
        "--global-only",
        action="store_true",
        help="Only migrate old global responses/settings, not group-local data.",
    )
    parser.add_argument(
        "--no-global",
        action="store_true",
        help="Only migrate group-local data, not old global responses/settings.",
    )
    parser.add_argument(
        "--broadcast-only",
        action="store_true",
        help="Only migrate broadcast targets from old groups/users into chat_logs.",
    )
    parser.add_argument(
        "--skip-chat-logs",
        action="store_true",
        help="Do not migrate old groups/users into chat_logs for broadcast.",
    )
    parser.add_argument(
        "--skip-users",
        action="store_true",
        help="Do not migrate old users as private broadcast targets.",
    )
    parser.add_argument(
        "--include-all-users",
        action="store_true",
        help=(
            "Migrate every old users document into private broadcast targets. "
            "By default, only users with private_interacted=true are migrated."
        ),
    )
    parser.add_argument(
        "--clear-target",
        action="store_true",
        help="Delete current global autoreply SQLite data before migrating.",
    )
    parser.add_argument(
        "--clear-chat-logs",
        action="store_true",
        help="Delete current SQLite chat_logs before migrating broadcast targets.",
    )
    parser.add_argument(
        "--list-source",
        action="store_true",
        help="List source MongoDB counts and exit.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write changes. Without this, the script runs a dry-run.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.global_only and args.no_global:
        print("--global-only and --no-global cannot be used together.", file=sys.stderr)
        return 2
    if args.broadcast_only and (
        args.global_only or args.no_global or args.skip_chat_logs or args.clear_target
    ):
        print(
            "--broadcast-only cannot be combined with --global-only, --no-global, "
            "--skip-chat-logs, or --clear-target.",
            file=sys.stderr,
        )
        return 2
    if not args.target_db.exists() and not args.list_source:
        print(f"Target database does not exist: {args.target_db}", file=sys.stderr)
        return 2

    client = connect_mongo(args.mongo_uri)
    try:
        db = client[args.mongo_db]
        if args.list_source:
            list_source(db)
            return 0

        target = connect_sqlite(args.target_db)
        try:
            ensure_target_schema(target)
            if args.clear_target:
                clear_autoreply_target(target)
            if args.clear_chat_logs:
                clear_chat_logs_target(target)

            counts: dict[str, int] = {}
            if not args.broadcast_only and not args.no_global:
                counts["settings"] = migrate_settings(db, target)
                counts.update(migrate_global_data(db, target))
            if not args.broadcast_only and not args.global_only:
                counts.update(migrate_group_data(db, target, args.source_chat_id))
            if not args.skip_chat_logs:
                counts.update(
                    migrate_chat_logs(
                        db,
                        target,
                        args.source_chat_id,
                        include_users=not args.skip_users,
                        include_all_users=args.include_all_users,
                    )
                )

            if args.apply:
                target.commit()
                action = "Migrated"
            else:
                target.rollback()
                action = "Dry run"

            group_filter = ", ".join(map(str, args.source_chat_id)) or "all groups"
            print(f"{action} MongoDB data into SQLite.")
            print(f"Group filter: {group_filter}")
            for key, count in counts.items():
                print(f"  {key}: {count}")
            if not args.apply:
                print("\nNo changes were written. Re-run with --apply to migrate.")
            return 0
        finally:
            target.close()
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
