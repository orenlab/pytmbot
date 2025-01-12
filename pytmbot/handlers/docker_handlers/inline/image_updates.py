import json

from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot.adapters.docker.updates import DockerImageUpdater
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()


# func=lambda call: call.data.startswith('__check_updates__')
@logger.catch()
@logger.session_decorator
def handle_image_updates(call: CallbackQuery, bot: TeleBot):
    """
    Handles the callback for images updates.

    Args:
        call (CallbackQuery): The callback query object.
        bot (TeleBot): The Telegram bot object.

    Returns:
        None
    """
    updater = DockerImageUpdater()
    updater.initialize()

    context_json = updater.to_json()
    context = json.loads(context_json)

    if not context or all(not image_info["updates"] for image_info in context.values()):
        return bot.answer_callback_query(
            call.id,
            text="No updates found for any images.",
            show_alert=True,
        )

    prepared_context = prepare_context_for_render(context)

    with Compiler(template_name="d_updates.jinja2", **prepared_context) as compiler:
        formatted_context = compiler.compile()

    return bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=formatted_context,
        parse_mode="Markdown",
    )


def prepare_context_for_render(context):
    updates = {}
    no_updates = []

    for repo, info in context.items():
        if not info["updates"]:
            no_updates.append(repo)
            continue

        updates[repo] = {
            "current_tag": info["updates"][0]["current_tag"],
            "created_at_local": info["updates"][0]["created_at_local"],
            "updates": [
                {
                    "newer_tag": update["newer_tag"],
                    "created_at_remote": update["created_at_remote"],
                }
                for update in info["updates"]
            ],
        }

    return {"updates": updates, "no_updates": no_updates}
