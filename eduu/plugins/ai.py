# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from time import monotonic

from hydrogram import Client, filters, raw
from hydrogram.enums import ChatAction, ParseMode
from hydrogram.types import Message

from config import GEMINI_API_KEY, PREFIXES
from eduu.utils import commands
from eduu.utils.localization import Strings, use_chat_lang

try:
    from google import genai
except ImportError:
    genai = None

SYSTEM_PROMPT = """Personality:
- Casual and direct. No fluff, no filler phrases like "Great question!" or "Certainly!".
- Be honest. If you don't know, say so plainly.
- Myanmar (Burmese) is the preferred language. But match the language the user writes in.
- Keep English words if there is no direct translation or is awkward to translate. Use modern language features.
- Use emojis when needed, but don't overuse them.
- No markdown, no bullet points, no bold, no headers. Plain text only unless the user explicitly asks for formatting.
- Most importantly be human. Don't sound like a bot. Talk like a normal person would.
- Be relatable.
- You have no memory of past conversations. Never ask follow-up questions or reference previous context. Work only with what's given right now.

Rules:
- Mirror the user's tone and energy. Formal user = formal. Casual/slangy = loosen up. Angry = stay calm but don't be stiff.
- Never start a reply with sycophantic openers.
- Keep replies short unless the question genuinely needs depth.
- If the question is dumb, you can say so nicely.
- Light humor only when it fits, but don't force it."""

EDIT_STREAM_UPDATE_INTERVAL = 0.8


def _init_genai():
    """Initialize the genai client if available and API key is set."""
    if not genai or not GEMINI_API_KEY:
        return None
    try:
        return genai.Client(api_key=GEMINI_API_KEY)
    except Exception:
        return None


async def _send_typing(c: Client, chat_id: int, message_thread_id: int | None = None) -> None:
    try:
        peer = await c.resolve_peer(chat_id)
        request = (
            raw.functions.messages.SetTyping(peer=peer, action=ChatAction.TYPING.value())
            if message_thread_id is None
            else raw.functions.messages.SetTyping(
                peer=peer,
                action=ChatAction.TYPING.value(),
                top_msg_id=message_thread_id,
            )
        )
        await c.invoke(request)
    except Exception:
        # Typing is cosmetic and must never prevent an AI response.
        pass


async def _update_text_stream(message: Message, text: str) -> None:
    try:
        await message.edit_text(text[:4096], parse_mode=ParseMode.DISABLED)
    except Exception:
        pass


@Client.on_message(filters.command("ai", PREFIXES))
@use_chat_lang
async def ai_command(c: Client, m: Message, s: Strings):
    """AI command handler - supports both reply and parameter based."""
    client = _init_genai()
    if not client:
        await m.reply_text(s("ai_no_service"))
        return

    # Get the input text
    input_text = None

    # Get reply text if available
    reply_text = None
    if m.reply_to_message:
        if m.reply_to_message.text:
            reply_text = m.reply_to_message.text
        elif m.reply_to_message.caption:
            reply_text = m.reply_to_message.caption

    # Get command parameters if available
    param_text = None
    if len(m.command) > 1:
        param_text = " ".join(m.command[1:])

    # Combine both if available, otherwise use whichever is available
    if reply_text and param_text:
        input_text = f"{reply_text}\n\n{param_text}"
    elif reply_text:
        input_text = reply_text
    elif param_text:
        input_text = param_text
    else:
        await m.reply_text(s("ai_no_input"))
        return

    if not input_text or not input_text.strip():
        await m.reply_text(s("ai_no_input"))
        return

    text_stream_message = await m.reply_text("...", parse_mode=ParseMode.DISABLED)

    try:
        await _send_typing(c, m.chat.id, m.message_thread_id)

        # Build context with separate user info for each input
        context_parts = [SYSTEM_PROMPT, "\nContext:"]
        
        # Add reply user context if available
        if reply_text:
            reply_user = m.reply_to_message.from_user.mention if m.reply_to_message.from_user else "Unknown"
            context_parts.append(f"- Replied User: {reply_user}")
            context_parts.append(f"- Replied Message: {reply_text}")
        
        # Add current user context if param text is provided
        if param_text:
            current_user = m.from_user.mention if m.from_user else "Unknown"
            context_parts.append(f"- Current User: {current_user}")
            context_parts.append(f"- Current Message: {param_text}")
        elif reply_text:
            # If only reply text, still add current user context
            current_user = m.from_user.mention if m.from_user else "Unknown"
            context_parts.append(f"- User: {current_user}")
        
        context_parts.append(f"- Chat: {m.chat.title if m.chat.title else 'Direct Message'}")
        context_parts.append(f"\nFull context:\n{input_text}")
        
        context = "\n".join(context_parts)

        response_stream = await client.aio.models.generate_content_stream(
            model="gemini-3.1-flash-lite",
            contents=context,
        )
        last_text_update = 0.0
        response_parts = []
        async for response in response_stream:
            chunk = response.text if hasattr(response, "text") else str(response)
            if not chunk:
                continue
            response_parts.append(chunk)
            partial_response = "".join(response_parts)
            now = monotonic()
            if now - last_text_update < EDIT_STREAM_UPDATE_INTERVAL:
                continue
            await _update_text_stream(text_stream_message, partial_response)
            last_text_update = now

        ai_response = "".join(response_parts)

        if not ai_response or not ai_response.strip():
            await _update_text_stream(text_stream_message, s("ai_empty_response"))
            return

        await _update_text_stream(text_stream_message, ai_response)
        for index in range(4096, len(ai_response), 4096):
            await m.reply_text(
                ai_response[index : index + 4096],
                parse_mode=ParseMode.DISABLED,
            )

    except Exception as e:
        error_msg = s("ai_error").format(error=str(e)[:100])
        await _update_text_stream(text_stream_message, error_msg)


commands.add_command("ai", "ai")
