# SPDX-License-Identifier: MIT

from __future__ import annotations

import asyncio
import json
import os
import re
import requests
import shutil
import subprocess
import sys
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

from config import PREFIXES, TOKEN
from eduu.database.tiktok import get_tiktok_autodl, set_tiktok_autodl
from eduu.utils import check_perms, commands
from eduu.utils.localization import Strings, use_chat_lang

BOT_API_URL = f"https://api.telegram.org/bot{TOKEN}"
TIKTOK_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.|vm\.|vt\.)?tiktok\.com/[^\s<>()]+",
    re.IGNORECASE,
)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".aac", ".ogg", ".opus"}
MEDIA_GROUP_LIMIT = 10
GALLERY_DL_OUTPUT_DIR = Path("gallery-dl")


class GalleryDownloadError(RuntimeError):
    pass


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


def _is_tiktok_photo_url(url: str) -> bool:
    return "/photo/" in url.casefold()


def _tiktok_post_id(url: str) -> str | None:
    match = re.search(r"/(?:photo|video)/(\d+)", url)
    return match.group(1) if match else None


def _download_tiktok(url: str, directory: str) -> tuple[list[Path], dict[str, Any]]:
    output = str(Path(directory) / "%(id).80s-%(autonumber)03d.%(ext)s")
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
    files = sorted(
        (
            path
            for path in Path(directory).iterdir()
            if path.is_file() and not path.name.endswith((".part", ".ytdl"))
        ),
        key=lambda path: path.name,
    )
    if not files:
        raise FileNotFoundError("yt-dlp did not create a media file.")
    videos = [path for path in files if path.suffix.casefold() in VIDEO_EXTENSIONS]
    if not videos:
        raise FileNotFoundError("yt-dlp did not create a video file.")
    return videos, info


def _download_tiktok_slideshow(url: str, directory: str) -> tuple[list[Path], dict[str, Any]]:
    cache_dir = Path(directory) / ".cache"
    env = os.environ.copy()
    env["XDG_CACHE_HOME"] = str(cache_dir)
    post_id = _tiktok_post_id(url)
    command = [
        sys.executable,
        "-m",
        "gallery_dl",
        url,
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        env=env,
        text=True,
        timeout=180,
    )
    files = _collect_gallery_dl_files(post_id, Path(directory))
    if not files:
        if completed.returncode != 0:
            error = completed.stderr.strip() or completed.stdout.strip() or "gallery-dl failed"
            raise GalleryDownloadError(error[-500:])
        raise GalleryDownloadError("gallery-dl did not create a media file.")

    selected_files = _ordered_slideshow_files(files)
    return selected_files, _gallery_info(selected_files)


def _collect_gallery_dl_files(post_id: str | None, target_dir: Path) -> list[Path]:
    source_files = sorted(
        (
            path
            for path in GALLERY_DL_OUTPUT_DIR.rglob("*")
            if path.is_file()
            and not path.name.endswith((".part", ".ytdl"))
            and (post_id is None or post_id in path.name)
        ),
        key=lambda path: path.name,
    )
    copied_files = []
    for source in source_files:
        target = target_dir / source.name
        shutil.copy2(source, target)
        copied_files.append(target)
        try:
            source.unlink()
        except OSError:
            pass
    _cleanup_empty_gallery_dirs()
    return copied_files


def _cleanup_empty_gallery_dirs() -> None:
    if not GALLERY_DL_OUTPUT_DIR.exists():
        return
    for directory in sorted(
        (path for path in GALLERY_DL_OUTPUT_DIR.rglob("*") if path.is_dir()),
        key=lambda path: len(path.parts),
        reverse=True,
    ):
        try:
            directory.rmdir()
        except OSError:
            pass
    try:
        GALLERY_DL_OUTPUT_DIR.rmdir()
    except OSError:
        pass


def _ordered_slideshow_files(files: list[Path]) -> list[Path]:
    images = [path for path in files if path.suffix.casefold() in IMAGE_EXTENSIONS]
    audio = [path for path in files if path.suffix.casefold() in AUDIO_EXTENSIONS]
    if images:
        return [*images, *audio]
    return files


def _gallery_info(paths: list[Path]) -> dict[str, Any]:
    first = paths[0]
    uploader = _gallery_uploader(first)
    title = _gallery_title(first)
    return {
        "title": title or "TikTok slideshow",
        "description": title or "",
        "uploader": uploader,
    }


def _gallery_uploader(path: Path) -> str:
    parts = path.parts
    if len(parts) >= 3 and parts[-3] == "tiktok":
        return parts[-2]
    if len(parts) >= 2:
        return parts[-2]
    return ""


def _gallery_title(path: Path) -> str:
    stem = path.stem
    stem = re.sub(r"\s+\[[^\]]+\]$", "", stem)
    stem = re.sub(r"^\d+(?:_\d+)?\s*", "", stem).strip()
    if stem.startswith("(") and ")" in stem:
        stem = stem[1:]
    return stem.strip()


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
            if _is_tiktok_photo_url(url):
                paths, info = await asyncio.to_thread(_download_tiktok_slideshow, url, directory)
            else:
                paths, info = await asyncio.to_thread(_download_tiktok, url, directory)
            caption = _caption(info, url)
            await _send_downloaded_media(c, m, paths, caption)
    except (DownloadError, GalleryDownloadError) as e:
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


async def _send_downloaded_media(
    c: Client,
    m: Message,
    paths: list[Path],
    caption: str,
) -> None:
    images = [path for path in paths if path.suffix.casefold() in IMAGE_EXTENSIONS]
    videos = [path for path in paths if path.suffix.casefold() in VIDEO_EXTENSIONS]
    audio = [path for path in paths if path.suffix.casefold() in AUDIO_EXTENSIONS]

    if images and not videos:
        await _send_photos(c, m, images, caption)
        for index, path in enumerate(audio):
            await c.send_audio(
                chat_id=m.chat.id,
                audio=str(path),
                caption=caption if index == 0 else "",
                reply_to_message_id=m.id if index == 0 else None,
            )
        return

    remaining = [
        path
        for path in paths
        if path.suffix.casefold() not in AUDIO_EXTENSIONS | IMAGE_EXTENSIONS
    ]
    if not videos and not remaining:
        raise FileNotFoundError("No video file was downloaded.")
    path = max(videos or remaining, key=lambda item: item.stat().st_size)
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


async def _send_photos(
    c: Client,
    m: Message,
    paths: list[Path],
    caption: str,
) -> None:
    if len(paths) == 1:
        try:
            await c.send_photo(
                chat_id=m.chat.id,
                photo=str(paths[0]),
                caption=caption,
                reply_to_message_id=m.id,
            )
            return
        except RPCError:
            await c.send_document(
                chat_id=m.chat.id,
                document=str(paths[0]),
                caption=caption,
                reply_to_message_id=m.id,
            )
            return

    for start in range(0, len(paths), MEDIA_GROUP_LIMIT):
        chunk = paths[start : start + MEDIA_GROUP_LIMIT]
        await asyncio.to_thread(
            _send_photo_album_via_bot_api,
            m,
            chunk,
            caption if start == 0 else "",
            reply_to_message_id=m.id if start == 0 else None,
        )


def _send_photo_album_via_bot_api(
    m: Message,
    paths: list[Path],
    caption: str,
    *,
    reply_to_message_id: int | None,
) -> None:
    media = []
    files = {}
    handles = []
    try:
        for index, path in enumerate(paths):
            field = f"photo{index}"
            media_item = {
                "type": "photo",
                "media": f"attach://{field}",
            }
            if index == 0 and caption:
                media_item["caption"] = caption
                media_item["parse_mode"] = "HTML"
            media.append(media_item)
            handle = path.open("rb")
            handles.append(handle)
            files[field] = (path.name, handle)

        data: dict[str, str | int] = {
            "chat_id": m.chat.id,
            "media": json.dumps(media),
        }
        if reply_to_message_id is not None:
            data["reply_to_message_id"] = reply_to_message_id

        response = requests.post(
            f"{BOT_API_URL}/sendMediaGroup",
            data=data,
            files=files,
            timeout=60,
        )
        result = response.json()
        if not result.get("ok"):
            raise RuntimeError(result.get("description", "sendMediaGroup failed"))
    finally:
        for handle in handles:
            handle.close()


async def _send_photos_individually(
    c: Client,
    m: Message,
    paths: list[Path],
    caption: str,
) -> None:
    for index, path in enumerate(paths):
        try:
            await c.send_photo(
                chat_id=m.chat.id,
                photo=str(path),
                caption=caption if index == 0 else "",
                reply_to_message_id=m.id if index == 0 else None,
            )
        except RPCError:
            await c.send_document(
                chat_id=m.chat.id,
                document=str(path),
                caption=caption if index == 0 else "",
                reply_to_message_id=m.id if index == 0 else None,
            )


@Client.on_message(filters.command("tiktok", PREFIXES))
@use_chat_lang
async def tiktok_command(c: Client, m: Message, s: Strings):
    arg = _command_arg(m)
    url = _first_tiktok_url(m, m.reply_to_message, extra_text=arg)
    if not url:
        await m.reply_text(s("tiktok_usage"))
        return
    await _download_and_send(c, m, url, s)


@Client.on_message(filters.command("tiktokautodl", PREFIXES))
@use_chat_lang
async def tiktok_autodl_command(c: Client, m: Message, s: Strings):
    arg = _command_arg(m).casefold()
    if not m.chat or m.chat.type == ChatType.PRIVATE:
        await m.reply_text(s("tiktok_autodl_group_only"))
        return
    if arg in {"", "status"}:
        enabled = await get_tiktok_autodl(m.chat.id)
        await m.reply_text(
            s("tiktok_autodl_status").format(
                state=s("general_enabled") if enabled else s("general_disabled")
            )
        )
        return
    if arg not in {"on", "off"}:
        await m.reply_text(s("tiktok_autodl_usage"))
        return
    if not await check_perms(m, ChatPrivileges(can_change_info=True), True, s):
        return
    enabled = arg == "on"
    await set_tiktok_autodl(m.chat.id, enabled)
    await m.reply_text(s("tiktok_autodl_enabled" if enabled else "tiktok_autodl_disabled"))


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


commands.add_command("tiktok", "downloads")
commands.add_command("tiktokautodl", "downloads")
