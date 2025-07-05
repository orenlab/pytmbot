import json
from typing import Dict, List, Union

from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot.adapters.docker.updates import DockerImageUpdater, UpdaterStatus
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()


@logger.catch()
@logger.session_decorator
def handle_image_updates(call: CallbackQuery, bot: TeleBot):
    """
    Handles the callback for Docker image updates.

    Args:
        call (CallbackQuery): The callback query object.
        bot (TeleBot): The Telegram bot object.

    Returns:
        None
    """
    updater = DockerImageUpdater()
    updater.initialize()

    response_json = updater.to_json()
    response = json.loads(response_json)

    # Handle rate limit
    if response["status"] == UpdaterStatus.RATE_LIMITED.name:
        return bot.answer_callback_query(
            call.id,
            text=f"Rate limit exceeded. Please try again in {response['data']['retry_after']} seconds.",
            show_alert=True,
        )

    # Handle errors
    if response["status"] == UpdaterStatus.ERROR.name:
        return bot.answer_callback_query(
            call.id,
            text=f"Error checking updates: {response['message']}",
            show_alert=True,
        )

    # Handle success with no updates
    if not response["data"] or all(
        not image_info["updates"] for image_info in response["data"].values()
    ):
        return bot.answer_callback_query(
            call.id,
            text="No updates found for any images.",
            show_alert=True,
        )

    # Process updates
    prepared_context = prepare_context_for_render(response["data"])

    with Compiler(template_name="d_updates.jinja2", **prepared_context) as compiler:
        formatted_context = compiler.compile()

    return bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=formatted_context,
        parse_mode="Markdown",
    )


def prepare_context_for_render(
    data: Dict[str, Dict[str, List[dict]]]
) -> Dict[str, Union[Dict[str, Dict], List[str]]]:
    """
    Prepares the context for template rendering.

    Args:
        data: Dictionary containing update information for repositories

    Returns:
        Dictionary with prepared context for rendering
    """
    updates = {}
    no_updates = []

    for repo, info in data.items():
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
