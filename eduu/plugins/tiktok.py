# SPDX-License-Identifier: MIT

from __future__ import annotations

import asyncio
import re
from html import escape
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from hydrogram import Client, StopPropagation, filters
from hydrogram.enums import ChatType, MessageEntityType
from hydrogram.errors import RPCError
from hydrogram.types import ChatPrivileges, Message
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from config import PREFIXES
from eduu.database.tiktok import get_tiktok_autodl, set_tiktok_autodl
from eduu.utils import check_perms, commands
from eduu.utils.localization import Strings, use_chat_lang

TIKTOK_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.|vm\.|vt\.)?tiktok\.com/[^\s<>()]+",
    re.IGNORECASE,
)


def _command_arg(m: Message) -> str:
    parts = (m.text or m.caption or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) == 2 else ""


def _normalize_url(url: str) -> str:
    url = url.strip().rstrip(".,!?)]}>")
    if not url.casefold().startswith(("http://", "https://")):
        return f"https://{url}"
    return url


def _urls_from_message(m: Message | None) -> list[str]:
    if not m:
        return []
    text = m.text or m.caption or ""
    entities = m.entities or m.caption_entities or []
    urls = []
    for entity in entities:
        if entity.type == MessageEntityType.URL:
            urls.append(text[entity.offset : entity.offset + entity.length])
        elif entity.type == MessageEntityType.TEXT_LINK and entity.url:
            urls.append(entity.url)
    urls.extend(TIKTOK_RE.findall(text))
    seen = set()
    return [_normalize_url(url) for url in urls if not (url in seen or seen.add(url))]


def _first_tiktok_url(*messages: Message | None, extra_text: str = "") -> str | None:
    for url in TIKTOK_RE.findall(extra_text):
        return _normalize_url(url)
    for message in messages:
        for url in _urls_from_message(message):
            if TIKTOK_RE.search(url):
                return url
    return None


def _download_tiktok(url: str, directory: str) -> tuple[Path, dict[str, Any]]:
    output = str(Path(directory) / "%(id).80s.%(ext)s")
    options = {
        "format": "bv*+ba/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "outtmpl": output,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": True,
    }
    with YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=True)
    files = [path for path in Path(directory).iterdir() if path.is_file()]
    if not files:
        raise FileNotFoundError("yt-dlp did not create a media file.")
    return max(files, key=lambda path: path.stat().st_size), info


def _caption(info: dict[str, Any], source_url: str) -> str:
    title = info.get("title") or info.get("description") or "TikTok"
    uploader = info.get("uploader") or info.get("channel") or ""
    lines = [f"<b>{escape(str(title)[:180])}</b>"]
    if uploader:
        lines.append(f"by {escape(str(uploader)[:80])}")
    lines.append(f"<a href=\"{escape(source_url)}\">Source</a>")
    return "\n".join(lines)[:1024]


async def _download_and_send(c: Client, m: Message, url: str, s: Strings) -> bool:
    status = await m.reply_text(s("tiktok_downloading"))
    try:
        with TemporaryDirectory(prefix="eduu_tiktok_") as directory:
            path, info = await asyncio.to_thread(_download_tiktok, url, directory)
            caption = _caption(info, url)
            try:
                await c.send_video(
                    chat_id=m.chat.id,
                    video=str(path),
                    caption=caption,
                    supports_streaming=True,
                    reply_to_message_id=m.id,
                )
            except RPCError:
                await c.send_document(
                    chat_id=m.chat.id,
                    document=str(path),
                    caption=caption,
                    reply_to_message_id=m.id,
                )
    except DownloadError as e:
        await status.edit_text(s("tiktok_download_failed").format(error=escape(str(e)[:250])))
        return False
    except Exception as e:
        await status.edit_text(s("tiktok_download_failed").format(error=escape(str(e)[:250])))
        return False

    try:
        await status.delete()
    except RPCError:
        pass
    return True


@Client.on_message(filters.command("tiktok", PREFIXES))
@use_chat_lang
async def tiktok_command(c: Client, m: Message, s: Strings):
    arg = _command_arg(m)
    lowered = arg.casefold()

    if lowered in {"on", "off", "status"}:
        if not m.chat or m.chat.type == ChatType.PRIVATE:
            await m.reply_text(s("tiktok_autodl_group_only"))
            return
        if lowered == "status":
            enabled = await get_tiktok_autodl(m.chat.id)
            await m.reply_text(
                s("tiktok_autodl_status").format(
                    state=s("general_enabled") if enabled else s("general_disabled")
                )
            )
            return
        if not await check_perms(m, ChatPrivileges(can_change_info=True), True, s):
            return
        enabled = lowered == "on"
        await set_tiktok_autodl(m.chat.id, enabled)
        await m.reply_text(
            s("tiktok_autodl_enabled" if enabled else "tiktok_autodl_disabled")
        )
        return

    url = _first_tiktok_url(m, m.reply_to_message, extra_text=arg)
    if not url:
        await m.reply_text(s("tiktok_usage"))
        return
    await _download_and_send(c, m, url, s)


@Client.on_message(filters.group & filters.incoming & ~filters.service, group=2)
@use_chat_lang
async def tiktok_auto_download(c: Client, m: Message, s: Strings):
    """Automatically download TikTok links from normal group messages and captions."""
    if not await get_tiktok_autodl(m.chat.id):
        return
    url = _first_tiktok_url(m)
    if not url:
        return
    await _download_and_send(c, m, url, s)
    raise StopPropagation


commands.add_command("tiktok", "tools")
