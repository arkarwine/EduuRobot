# SPDX-License-Identifier: MIT
# Copyright (c) 2018-2026 Amano LLC

from hydrogram import Client, filters
from hydrogram.types import Message
from hydrogram.enums import ChatAction

from config import PREFIXES, GEMINI_API_KEY
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


def _init_genai():
    """Initialize the genai client if available and API key is set."""
    if not genai or not GEMINI_API_KEY:
        return None
    try:
        return genai.Client(api_key=GEMINI_API_KEY)
    except Exception:
        return None


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

    # Try reply-based first
    if m.reply_to_message:
        if m.reply_to_message.text:
            input_text = m.reply_to_message.text
        elif m.reply_to_message.caption:
            input_text = m.reply_to_message.caption

    # If no reply text, try command parameters
    if not input_text:
        if len(m.command) > 1:
            input_text = " ".join(m.command[1:])
        else:
            await m.reply_text(s("ai_no_input"))
            return

    if not input_text or not input_text.strip():
        await m.reply_text(s("ai_no_input"))
        return

    # Send typing indicator
    await c.send_chat_action(m.chat.id, ChatAction.TYPING)

    try:
        # Build context
        context = f"{SYSTEM_PROMPT}\n\nContext:\n- User: {m.from_user.mention}\n- Chat: {m.chat.title if m.chat.title else "Direct Message"}\n\nUser message: {input_text}"

        # Call Gemini API
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite",
            contents=context,
        )

        ai_response = response.text if hasattr(response, 'text') else str(response)

        if not ai_response or not ai_response.strip():
            await m.reply_text(s("ai_empty_response"))
            return

        # Send response, split if too long
        if len(ai_response) > 4096:
            # Split into chunks
            chunks = [ai_response[i : i + 4096] for i in range(0, len(ai_response), 4096)]
            for chunk in chunks:
                await m.reply_text(chunk)
        else:
            await m.reply_text(ai_response)

    except Exception as e:
        error_msg = s("ai_error").format(error=str(e)[:100])
        await m.reply_text(error_msg)


commands.add_command("ai", "general")
