# SPDX-License-Identifier: MIT

from __future__ import annotations

import asyncio
import json
import re
from html import escape, unescape
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from hydrogram import Client, StopPropagation, filters
from hydrogram.enums import ChatType, MessageEntityType
from hydrogram.errors import RPCError
from hydrogram.types import ChatPrivileges, InputMediaPhoto, Message
from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from config import PREFIXES
from eduu.database.tiktok import get_tiktok_autodl, set_tiktok_autodl
from eduu.utils import check_perms, commands, http
from eduu.utils.localization import Strings, use_chat_lang

TIKTOK_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.|vm\.|vt\.)?tiktok\.com/[^\s<>()]+",
    re.IGNORECASE,
)
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}
MEDIA_GROUP_LIMIT = 10
TIKTOK_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
UNIVERSAL_DATA_RE = re.compile(
    r'<script[^>]+id=["\']__UNIVERSAL_DATA_FOR_REHYDRATION__["\'][^>]*>'
    r"(?P<data>.*?)</script>",
    re.DOTALL,
)
SIGI_STATE_RE = re.compile(
    r'<script[^>]+id=["\']SIGI_STATE["\'][^>]*>(?P<data>.*?)</script>',
    re.DOTALL,
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
    return files, info


async def _download_tiktok_photos(url: str, directory: str) -> tuple[list[Path], dict[str, Any]] | None:
    response = await http.get(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "User-Agent": TIKTOK_USER_AGENT,
        },
    )
    response.raise_for_status()
    data = _extract_tiktok_json(response.text)
    if not data:
        return None

    urls = _extract_tiktok_photo_urls(data)
    if not urls:
        return None

    paths = []
    for index, image_url in enumerate(urls, start=1):
        image_response = await http.get(
            image_url,
            headers={"Referer": url, "User-Agent": TIKTOK_USER_AGENT},
        )
        image_response.raise_for_status()
        ext = _image_extension(image_url, image_response.headers.get("content-type", ""))
        path = Path(directory) / f"tiktok-photo-{index:02d}{ext}"
        path.write_bytes(image_response.content)
        paths.append(path)

    return paths, _extract_tiktok_photo_info(data)


def _extract_tiktok_json(html: str) -> dict[str, Any] | None:
    for pattern in (UNIVERSAL_DATA_RE, SIGI_STATE_RE):
        match = pattern.search(html)
        if not match:
            continue
        try:
            return json.loads(unescape(match.group("data")).strip())
        except json.JSONDecodeError:
            continue
    return None


def _extract_tiktok_photo_urls(data: dict[str, Any]) -> list[str]:
    urls = []
    for image in _iter_tiktok_photo_images(data):
        url = _best_image_url(image)
        if url and url not in urls:
            urls.append(url)
    return urls


def _iter_tiktok_photo_images(value: Any):
    if isinstance(value, dict):
        for key in ("imagePost", "image_post_info"):
            image_post = value.get(key)
            if isinstance(image_post, dict):
                images = image_post.get("images")
                if isinstance(images, list):
                    yield from images
        for item in value.values():
            yield from _iter_tiktok_photo_images(item)
    elif isinstance(value, list):
        for item in value:
            yield from _iter_tiktok_photo_images(item)


def _best_image_url(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("urlList", "url_list"):
            urls = value.get(key)
            if isinstance(urls, list):
                for url in urls:
                    if _looks_like_tiktok_image_url(url):
                        return url
        for key in ("imageURL", "image_url", "displayImage", "display_image"):
            url = _best_image_url(value.get(key))
            if url:
                return url
        for item in value.values():
            url = _best_image_url(item)
            if url:
                return url
    elif isinstance(value, list):
        for item in value:
            url = _best_image_url(item)
            if url:
                return url
    elif _looks_like_tiktok_image_url(value):
        return value
    return None


def _looks_like_tiktok_image_url(value: Any) -> bool:
    if not isinstance(value, str) or not value.startswith(("http://", "https://")):
        return False
    lower = value.casefold()
    return (
        "tiktokcdn" in lower
        and not any(marker in lower for marker in ("-music-", ".mp3", ".m4a", ".mp4"))
        and any(marker in lower for marker in ("image", "tos-", ".jpeg", ".jpg", ".webp", ".png"))
    )


def _extract_tiktok_photo_info(data: dict[str, Any]) -> dict[str, Any]:
    item = _find_tiktok_item(data) or {}
    author = item.get("author") if isinstance(item.get("author"), dict) else {}
    return {
        "title": item.get("desc") or item.get("title") or "TikTok photos",
        "description": item.get("desc") or "",
        "uploader": author.get("uniqueId") or author.get("nickname") or "",
    }


def _find_tiktok_item(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        if (
            isinstance(value.get("author"), dict)
            and ("desc" in value or "imagePost" in value or "image_post_info" in value)
        ):
            return value
        for item in value.values():
            found = _find_tiktok_item(item)
            if found:
                return found
    elif isinstance(value, list):
        for item in value:
            found = _find_tiktok_item(item)
            if found:
                return found
    return None


def _image_extension(url: str, content_type: str) -> str:
    lower_type = content_type.casefold()
    if "png" in lower_type:
        return ".png"
    if "webp" in lower_type:
        return ".webp"
    if "jpeg" in lower_type or "jpg" in lower_type:
        return ".jpg"
    suffix = Path(url.split("?", 1)[0]).suffix.casefold()
    return suffix if suffix in IMAGE_EXTENSIONS else ".jpg"


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
            photo_result = await _download_tiktok_photos(url, directory)
            if photo_result:
                paths, info = photo_result
            else:
                paths, info = await asyncio.to_thread(_download_tiktok, url, directory)
            caption = _caption(info, url)
            await _send_downloaded_media(c, m, paths, caption)
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


async def _send_downloaded_media(
    c: Client,
    m: Message,
    paths: list[Path],
    caption: str,
) -> None:
    images = [path for path in paths if path.suffix.casefold() in IMAGE_EXTENSIONS]
    videos = [path for path in paths if path.suffix.casefold() in VIDEO_EXTENSIONS]

    if images and not videos:
        await _send_photos(c, m, images, caption)
        return

    path = max(videos or paths, key=lambda item: item.stat().st_size)
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

    try:
        for start in range(0, len(paths), MEDIA_GROUP_LIMIT):
            chunk = paths[start : start + MEDIA_GROUP_LIMIT]
            media = [
                InputMediaPhoto(
                    media=str(path),
                    caption=caption if start == 0 and index == 0 else "",
                )
                for index, path in enumerate(chunk)
            ]
            await c.send_media_group(
                chat_id=m.chat.id,
                media=media,
                reply_to_message_id=m.id if start == 0 else None,
            )
    except RPCError:
        for index, path in enumerate(paths):
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


commands.add_command("tiktok", "downloads")
