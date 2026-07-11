# SPDX-License-Identifier: MIT

from __future__ import annotations

import re
from html import escape
from typing import Any

from hydrogram import Client, filters
from hydrogram.enums import MessageEntityType
from hydrogram.types import Message

from config import PREFIXES, TOKEN
from eduu.utils import commands, http
from eduu.utils.custom_emoji import render_custom_emoji_text
from eduu.utils.localization import Strings, use_chat_lang

BOT_API_URL = f"https://api.telegram.org/bot{TOKEN}"
ADD_EMOJI_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/(?:addemoji|addstickers)/(?P<name>[A-Za-z0-9_]+)",
    re.IGNORECASE,
)
CUSTOM_EMOJI_ID_RE = re.compile(r"(?<!\d)\d{10,20}(?!\d)")
MAX_MESSAGE_LENGTH = 3900
CUSTOM_EMOJI_LOOKUP_BATCH_SIZE = 200


def _command_arg(m: Message) -> str:
    parts = (m.text or m.caption or "").split(maxsplit=1)
    return parts[1].strip() if len(parts) == 2 else ""


def _is_custom_emoji_entity(entity: Any) -> bool:
    entity_type = getattr(entity, "type", None)
    custom_type = getattr(MessageEntityType, "CUSTOM_EMOJI", None)
    return (
        entity_type == custom_type
        or str(entity_type).casefold().endswith("custom_emoji")
        or str(entity_type).casefold() == "messageentitytype.custom_emoji"
    )


def _custom_emoji_ids_from_message(message: Message | None) -> list[tuple[str, str]]:
    if message is None:
        return []
    text = message.text or message.caption or ""
    entities = message.entities or message.caption_entities or []
    results = []
    seen = set()
    for entity in entities:
        custom_emoji_id = getattr(entity, "custom_emoji_id", None)
        if not custom_emoji_id or not _is_custom_emoji_entity(entity):
            continue
        fallback = text[entity.offset : entity.offset + entity.length] or "emoji"
        key = (fallback, custom_emoji_id)
        if key not in seen:
            seen.add(key)
            results.append(key)
    return results


def _pack_names_from_message(message: Message | None, extra_text: str = "") -> list[str]:
    texts = [extra_text]
    if message is not None:
        texts.append(message.text or message.caption or "")
        entities = message.entities or message.caption_entities or []
        for entity in entities:
            if getattr(entity, "url", None):
                texts.append(entity.url)

    names = []
    for text in texts:
        for match in ADD_EMOJI_RE.finditer(text or ""):
            name = match.group("name")
            if name not in names:
                names.append(name)
    return names


async def _get_sticker_set(name: str) -> dict[str, Any]:
    response = await http.post(f"{BOT_API_URL}/getStickerSet", json={"name": name})
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("description", "getStickerSet failed"))
    return data["result"]


async def _custom_emoji_ids_from_pack(name: str) -> list[tuple[str, str]]:
    sticker_set = await _get_sticker_set(name)
    results = []
    seen = set()
    for sticker in sticker_set.get("stickers", []):
        custom_emoji_id = sticker.get("custom_emoji_id")
        if not custom_emoji_id:
            continue
        emoji = sticker.get("emoji") or "emoji"
        key = (emoji, custom_emoji_id)
        if key not in seen:
            seen.add(key)
            results.append(key)
    return results


def _custom_emoji_ids_from_text(text: str) -> list[str]:
    return list(dict.fromkeys(CUSTOM_EMOJI_ID_RE.findall(text or "")))


async def _custom_emoji_rows_from_ids(
    custom_emoji_ids: list[str],
) -> list[tuple[str, str]]:
    stickers_by_id: dict[str, dict[str, Any]] = {}
    for offset in range(0, len(custom_emoji_ids), CUSTOM_EMOJI_LOOKUP_BATCH_SIZE):
        batch = custom_emoji_ids[offset : offset + CUSTOM_EMOJI_LOOKUP_BATCH_SIZE]
        response = await http.post(
            f"{BOT_API_URL}/getCustomEmojiStickers",
            json={"custom_emoji_ids": batch},
        )
        data = response.json()
        if not data.get("ok"):
            raise RuntimeError(data.get("description", "getCustomEmojiStickers failed"))
        for sticker in data.get("result", []):
            custom_emoji_id = str(sticker.get("custom_emoji_id", ""))
            if custom_emoji_id:
                stickers_by_id[custom_emoji_id] = sticker

    return [
        (stickers_by_id[custom_emoji_id].get("emoji") or "emoji", custom_emoji_id)
        for custom_emoji_id in custom_emoji_ids
        if custom_emoji_id in stickers_by_id
    ]


def _format_results(title: str, rows: list[tuple[str, str]]) -> str:
    lines = [f"<b>{escape(title)}</b>", ""]
    for emoji, custom_emoji_id in rows:
        fallback = escape(emoji)
        lines.append(
            f'<tg-emoji emoji-id="{custom_emoji_id}">{fallback}</tg-emoji>'
            f'[<code>{custom_emoji_id}</code>]'
        )
    return "\n".join(lines)


async def _reply_chunks(m: Message, text: str) -> None:
    chunks = []
    current = ""
    for line in text.splitlines():
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > MAX_MESSAGE_LENGTH:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    for chunk in chunks:
        await _send_html_reply(m, chunk)


async def _send_html_reply(m: Message, text: str) -> None:
    text = render_custom_emoji_text(text)
    response = await http.post(
        f"{BOT_API_URL}/sendMessage",
        json={
            "chat_id": m.chat.id,
            "text": text,
            "parse_mode": "HTML",
            "reply_to_message_id": m.id,
        },
    )
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError(data.get("description", "sendMessage failed"))


@Client.on_message(filters.command("emoji", PREFIXES))
@use_chat_lang
async def emoji_ids(c: Client, m: Message, s: Strings):
    arg = _command_arg(m)
    rows = _custom_emoji_ids_from_message(m)
    rows.extend(
        row for row in _custom_emoji_ids_from_message(m.reply_to_message) if row not in rows
    )

    pack_names = _pack_names_from_message(m, arg)
    if m.reply_to_message:
        pack_names.extend(
            name
            for name in _pack_names_from_message(m.reply_to_message)
            if name not in pack_names
        )

    pack_errors = []
    for name in pack_names:
        try:
            pack_rows = await _custom_emoji_ids_from_pack(name)
        except Exception as e:
            pack_errors.append(f"{name}: {escape(str(e)[:250])}")
            continue
        rows.extend(row for row in pack_rows if row not in rows)

    lookup_errors = []
    raw_ids = _custom_emoji_ids_from_text(arg)
    if m.reply_to_message:
        reply_text = m.reply_to_message.text or m.reply_to_message.caption or ""
        raw_ids.extend(
            custom_emoji_id
            for custom_emoji_id in _custom_emoji_ids_from_text(reply_text)
            if custom_emoji_id not in raw_ids
        )
    if raw_ids:
        try:
            id_rows = await _custom_emoji_rows_from_ids(raw_ids)
        except Exception as e:
            lookup_errors.append(escape(str(e)[:250]))
        else:
            found_ids = {custom_emoji_id for _, custom_emoji_id in id_rows}
            missing_ids = [
                custom_emoji_id
                for custom_emoji_id in raw_ids
                if custom_emoji_id not in found_ids
            ]
            if missing_ids:
                lookup_errors.append(
                    s("emoji_ids_not_found").format(
                        ids=", ".join(
                            f"<code>{custom_emoji_id}</code>"
                            for custom_emoji_id in missing_ids
                        )
                    )
                )
            existing_ids = {custom_emoji_id for _, custom_emoji_id in rows}
            rows.extend(row for row in id_rows if row[1] not in existing_ids)

    if not rows:
        usage = s("emoji_usage")
        if pack_errors:
            usage += "\n\n" + s("emoji_pack_errors").format(
                errors="\n".join(f"• {error}" for error in pack_errors)
            )
        if lookup_errors:
            usage += "\n\n" + s("emoji_lookup_errors").format(
                errors="\n".join(f"• {error}" for error in lookup_errors)
            )
        await m.reply_text(usage)
        return

    text = _format_results(s("emoji_title").format(count=len(rows)), rows)
    if pack_errors:
        text += "\n\n" + s("emoji_pack_errors").format(
            errors="\n".join(f"• {error}" for error in pack_errors)
        )
    if lookup_errors:
        text += "\n\n" + s("emoji_lookup_errors").format(
            errors="\n".join(f"• {error}" for error in lookup_errors)
        )
    await _reply_chunks(m, text)


commands.add_command("emoji", "tools")

