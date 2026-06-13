# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

import logging

import aiosqlite

from config import DATABASE_PATH

logger = logging.getLogger(__name__)


class Database:
    def __init__(self):
        self.conn: aiosqlite.Connection = None
        self.path: str = DATABASE_PATH
        self.is_connected: bool = False

    async def connect(self):
        # Open the connection
        conn = await aiosqlite.connect(self.path)

        # Define the tables
        await conn.executescript(
            """
        CREATE TABLE IF NOT EXISTS groups(
            chat_id INTEGER PRIMARY KEY,
            welcome TEXT,
            welcome_enabled INTEGER,
            rules TEXT,
            warns_limit INTEGER,
            chat_lang TEXT,
            cached_admins,
            antichannelpin INTEGER,
            delservicemsgs INTEGER,
            antispam INTEGER DEFAULT 1,
            warn_action TEXT
        );

        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            chat_lang TEXT
        );

        CREATE TABLE IF NOT EXISTS channels(
            chat_id INTEGER PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS was_restarted_at(
            chat_id INTEGER,
            message_id INTEGER
        );

        CREATE TABLE IF NOT EXISTS filters(
            chat_id INTEGER ,
            filter_name TEXT,
            raw_data TEXT,
            file_id TEXT,
            filter_type TEXT
        );

        CREATE TABLE IF NOT EXISTS notes(
            chat_id INTEGER ,
            note_name,
            raw_data,
            file_id,
            note_type
        );

        CREATE TABLE IF NOT EXISTS user_warns(
            user_id INTEGER,
            chat_id INTEGER,
            count INTEGER
        );

        CREATE TABLE IF NOT EXISTS spam_filters(
            chat_id INTEGER,
            word TEXT,
            UNIQUE(chat_id, word)
        );

        CREATE TABLE IF NOT EXISTS spam_filter_settings(
            chat_id INTEGER PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS antispam_settings(
            chat_id INTEGER PRIMARY KEY,
            enabled INTEGER DEFAULT 1,
            links INTEGER DEFAULT 1,
            forwards INTEGER DEFAULT 1,
            words INTEGER DEFAULT 1,
            flood INTEGER DEFAULT 1,
            repeats INTEGER DEFAULT 1,
            flood_limit INTEGER DEFAULT 6,
            flood_window INTEGER DEFAULT 8,
            repeat_limit INTEGER DEFAULT 3,
            repeat_window INTEGER DEFAULT 20,
            mute_minutes INTEGER DEFAULT 5
        );

        CREATE TABLE IF NOT EXISTS antispam_allowlist(
            chat_id INTEGER,
            kind TEXT,
            value TEXT,
            UNIQUE(chat_id, kind, value)
        );

        CREATE TABLE IF NOT EXISTS mention_all_settings(
            chat_id INTEGER PRIMARY KEY,
            batch_size INTEGER DEFAULT 5,
            delay_seconds INTEGER DEFAULT 2,
            hidden INTEGER DEFAULT 1,
            include_admins INTEGER DEFAULT 1,
            emoji TEXT DEFAULT '🔔'
        );

        CREATE TABLE IF NOT EXISTS chat_logs(
            chat_id INTEGER PRIMARY KEY,
            chat_type TEXT,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            chat_title TEXT
        );
        """
        )

        # Enable WAL
        await conn.execute("PRAGMA journal_mode=WAL")

        # Update the database
        await conn.commit()

        conn.row_factory = aiosqlite.Row

        self.conn = conn
        self.is_connected: bool = True

        logger.info("The database has been connected.")

    async def close(self):
        # Close the connection
        await self.conn.close()

        self.is_connected: bool = False

        logger.info("The database was closed.")

    def get_conn(self) -> aiosqlite.Connection:
        if not self.is_connected:
            raise RuntimeError("The database is not connected.")

        return self.conn


database = Database()
