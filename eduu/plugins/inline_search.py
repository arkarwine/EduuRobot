import html
from uuid import uuid4

from hydrogram import Client
from hydrogram.types import (
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent,
)

from eduu.utils import inline_commands
from eduu.utils.buttons import styled_button
from eduu.utils.localization import Strings, use_chat_lang
from eduu.utils.styled_messages import (
    answer_styled_inline_query,
    button_to_dict,
)


@Client.on_inline_query(group=2)
@use_chat_lang
async def inline_search(c: Client, q: InlineQuery, s: Strings):
    command = q.query.split(maxsplit=1)[0] if q.query else q.query

    results = inline_commands.search_commands(command)
    if not results:
        await q.answer(
            [
                InlineQueryResultArticle(
                    title=s("inline_cmds_no_results").format(query=command),
                    input_message_content=InputTextMessageContent(
                        s("inline_cmds_no_results").format(query=command)
                    ),
                )
            ],
            cache_time=0,
        )
        return

    articles = []
    for result in results:
        stripped_command = result["command"].split()[0]
        articles.append(
            {
                "type": "article",
                "id": str(uuid4()),
                "title": result["command"],
                "description": s(result["description_key"]),
                "input_message_content": {
                    "message_text": (
                        f"{html.escape(result['command'])}: {s(result['description_key'])}"
                    ),
                    "parse_mode": "HTML",
                },
                "reply_markup": {
                    "inline_keyboard": [
                        [
                            button_to_dict(
                                styled_button(
                                    text=s("inline_cmds_run_command_button").format(
                                        query=stripped_command
                                    ),
                                    switch_inline_query_current_chat=stripped_command,
                                    style="success",
                                )
                            )
                        ]
                    ]
                },
            }
        )
    await answer_styled_inline_query(q.id, articles)
