#!/usr/bin/env python3
"""Import exported global autoreply responses into SQLite."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sqlite3
from pathlib import Path


GLOBAL_AUTOREPLY_ID = 0


def nullable_int(value: str) -> int | None:
    value = value.strip()
    if not value or value.lower() == "null":
        return None
    return int(value)


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
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
        )
        """
    )


def read_rows(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        required = {
            "chat_id",
            "mode",
            "keywords",
            "response_type",
            "text",
            "source_chat_id",
            "source_message_id",
            "label",
            "created_at",
        }
        if not reader.fieldnames or not required.issubset(reader.fieldnames):
            missing = sorted(required - set(reader.fieldnames or []))
            raise ValueError(f"CSV is missing columns: {', '.join(missing)}")

        rows = []
        for line, row in enumerate(reader, start=2):
            chat_id = int(row["chat_id"]) if row["chat_id"].strip() else 0
            if chat_id != 0:
                raise ValueError(f"Line {line}: only global chat_id 0 rows are supported")

            mode = row["mode"].strip()
            if mode not in {"random", "keyword"}:
                raise ValueError(f"Line {line}: invalid mode {mode!r}")

            response_type = row["response_type"].strip()
            if response_type not in {"text", "message"}:
                raise ValueError(f"Line {line}: invalid response_type {response_type!r}")

            if row["keywords"].strip():
                try:
                    keywords = json.loads(row["keywords"])
                except json.JSONDecodeError as exc:
                    raise ValueError(f"Line {line}: invalid keywords JSON") from exc
                if not isinstance(keywords, list):
                    raise ValueError(f"Line {line}: keywords must be a JSON list")
                keywords_json = json.dumps(keywords, ensure_ascii=False)
            else:
                keywords_json = "[]"

            text = None if row["text"].strip().lower() == "null" else row["text"]
            source_chat_id = nullable_int(row["source_chat_id"])
            source_message_id = nullable_int(row["source_message_id"])

            if response_type == "text" and not text:
                raise ValueError(f"Line {line}: text response has no text")
            if response_type == "message" and (
                source_chat_id is None or source_message_id is None
            ):
                raise ValueError(
                    f"Line {line}: message response requires source chat and message IDs"
                )

            rows.append(
                {
                    "mode": mode,
                    "keywords": keywords_json,
                    "response_type": response_type,
                    "text": text,
                    "source_chat_id": source_chat_id,
                    "source_message_id": source_message_id,
                    "label": row["label"].strip() or None,
                    "created_at": row["created_at"].strip() or None,
                }
            )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("csv", type=Path)
    parser.add_argument("database", type=Path)
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", action="store_true")
    args = parser.parse_args()

    rows = read_rows(args.csv)
    print(
        f"CSV contains {len(rows)} rows "
        f"({sum(r['response_type'] == 'text' for r in rows)} text, "
        f"{sum(r['response_type'] == 'message' for r in rows)} copied messages)."
    )

    if not args.database.exists():
        raise SystemExit(f"Database does not exist: {args.database}")

    if args.backup:
        backup = args.database.with_name(args.database.name + ".backup")
        if args.apply:
            shutil.copy2(args.database, backup)
            print(f"Backup created: {backup}")
        else:
            print(f"Backup would be created: {backup}")

    conn = sqlite3.connect(args.database)
    try:
        ensure_schema(conn)
        existing = conn.execute(
            "SELECT COUNT(*) FROM autoreply_responses WHERE chat_id = ?",
            (GLOBAL_AUTOREPLY_ID,),
        ).fetchone()[0]
        print(
            f"{'Replace' if args.replace else 'Merge'} mode: "
            f"{existing} existing global rows."
        )
        if not args.apply:
            print("Dry run only; no changes written.")
            return 0

        conn.execute("BEGIN")
        if args.replace:
            conn.execute(
                "DELETE FROM autoreply_responses WHERE chat_id = ?",
                (GLOBAL_AUTOREPLY_ID,),
            )

        conn.executemany(
            """
            INSERT INTO autoreply_responses(
                chat_id, mode, keywords, response_type, text,
                source_chat_id, source_message_id, label, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    GLOBAL_AUTOREPLY_ID,
                    row["mode"],
                    row["keywords"],
                    row["response_type"],
                    row["text"],
                    row["source_chat_id"],
                    row["source_message_id"],
                    row["label"],
                    row["created_at"],
                )
                for row in rows
            ],
        )
        conn.commit()
        final = conn.execute(
            "SELECT COUNT(*) FROM autoreply_responses WHERE chat_id = ?",
            (GLOBAL_AUTOREPLY_ID,),
        ).fetchone()[0]
        print(f"Import complete: {final} total global rows.")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
