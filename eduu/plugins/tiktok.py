# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

import asyncio
import logging
import re
import tempfile
from pathlib import Path
from typing import Optional

from hydrogram import Client, filters
from hydrogram.enums import ParseMode
from hydrogram.types import Message
from yt_dlp import YoutubeDL

from config import PREFIXES
from eduu.database.tiktok import get_tiktok, toggle_tiktok
from eduu.utils import commands
from eduu.utils.decorators import require_admin
from eduu.utils.localization import Strings, use_chat_lang

logger = logging.getLogger(__name__)

TIKTOK_URL_REGEX = r"https?://(?:www\.)?(?:vm\.tiktok\.com/|tiktok\.com/[\w\-/.?&=]+)"

YTDLP_OPTS = {
    "format": "mp4",
    "outtmpl": "%(id)s.%(ext)s",
    "quiet": True,
    "no_warnings": True,
    "noplaylist": True,
    "writesubtitles": False,
    "writeautomaticsub": False,
    "no_check_certificate": True,
    "nocheckcertificate": True,
    "merge_output_format": "mp4",
}


def _download_tiktok_sync(url: str, download_path: Path) -> Optional[Path]:
    try:
        with YoutubeDL(YTDLP_OPTS) as ydl:
            info = ydl.extract_info(url, download=False)
            filename = ydl.prepare_filename(info)

        output_path = download_path / Path(filename).name
        with YoutubeDL({**YTDLP_OPTS, "outtmpl": str(output_path)}) as ydl:
            ydl.download([url])

        return output_path if output_path.exists() else None
    except Exception as exc:
        logger.exception("TikTok download failed for url %s", url)
        return None


async def _download_tiktok(url: str, download_path: Path) -> Optional[Path]:
    return await asyncio.to_thread(_download_tiktok_sync, url, download_path)


async def _send_video(c: Client, m: Message, file_path: Path, caption: str | None = None) -> bool:
    try:
        await c.send_video(
            chat_id=m.chat.id,
            video=str(file_path),
            caption=caption or "",
            parse_mode=ParseMode.HTML,
        )
        return True
    except Exception as exc:
        logger.exception("Failed to send TikTok video for %s", m.chat.id)
        await m.reply_text(f"Error sending video: {exc}")
        return False


async def _process_tiktok_url(c: Client, m: Message, url: str, s: Strings) -> None:
    status = await get_tiktok(m.chat.id)
    if not status:
        return

    message = await m.reply_text(s("tiktok_dl_start"))
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir)
        video = await _download_tiktok(url, path)

        if not video:
            await message.edit_text(s("tiktok_dl_failed"))
            return

        await message.edit_text(s("tiktok_dl_upload"))
        sent = await _send_video(c, m, video, s("tiktok_dl_caption"))
        if sent:
            try:
                await message.delete()
            except Exception:
                pass


@Client.on_message(
    filters.command("tiktok", PREFIXES)
    & ~filters.command(["tiktok on", "tiktok off"], PREFIXES)
    & filters.group
)
@require_admin()
@use_chat_lang
async def manual_tiktok_download(c: Client, m: Message, s: Strings):
    if len(m.command) < 2:
        await m.reply_text(s("tiktok_manual_usage"))
        return

    url = m.command[1]
    await _process_tiktok_url(c, m, url, s)


@Client.on_message(filters.command("tiktok on", PREFIXES) & filters.group)
@require_admin()
@use_chat_lang
async def enable_tiktok_auto(c: Client, m: Message, s: Strings):
    await toggle_tiktok(m.chat.id, True)
    await m.reply_text(s("tiktok_enable"))


@Client.on_message(filters.command("tiktok off", PREFIXES) & filters.group)
@require_admin()
@use_chat_lang
async def disable_tiktok_auto(c: Client, m: Message, s: Strings):
    await toggle_tiktok(m.chat.id, False)
    await m.reply_text(s("tiktok_disable"))


@Client.on_message(~filters.command(["tiktok", "tiktok on", "tiktok off"], PREFIXES) & filters.regex(TIKTOK_URL_REGEX) & filters.group)
@use_chat_lang
async def auto_tiktok_detect(c: Client, m: Message, s: Strings):
    if not await get_tiktok(m.chat.id):
        return

    url = m.text or m.caption or ""
    if not url:
        return

    match = re.search(TIKTOK_URL_REGEX, url)
    if not match:
        return

    await _process_tiktok_url(c, m, match.group(0), s)


commands.add_command("tiktok", "tools")
