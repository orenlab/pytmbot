#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot.adapters.docker.updates import DockerImageUpdater, UpdaterStatus
from pytmbot.handlers.handlers_util.callback_auth import (
    authorize_callback_request,
    parse_callback_target_user,
)
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()


@logger.catch()
@logger.session_decorator
def handle_image_updates(call: CallbackQuery, bot: TeleBot) -> None:
    """
    Handles the callback for Docker image updates.

    Args:
        call (CallbackQuery): The callback query object.
        bot (TeleBot): The Telegram bot object.

    Returns:
        None
    """
    try:
        target_user_id = parse_callback_target_user(
            call.data or "", "__check_updates__"
        )
    except ValueError:
        bot.answer_callback_query(
            call.id,
            text="Invalid image updates request format.",
            show_alert=True,
        )
        return None

    is_allowed, deny_reason = authorize_callback_request(
        call,
        target_user_id=target_user_id,
        require_owner_match=target_user_id is not None,
    )
    if not is_allowed:
        bot.answer_callback_query(call.id, text=deny_reason, show_alert=True)
        return None

    if call.message is None:
        bot.answer_callback_query(
            call.id,
            text="Cannot render image updates in this context.",
            show_alert=True,
        )
        return None

    updater = DockerImageUpdater()
    updater.initialize()

    response = updater.to_dict()

    # Handle rate limit
    if response["status"] == UpdaterStatus.RATE_LIMITED.name:
        bot.answer_callback_query(
            call.id,
            text=f"Rate limit exceeded. Please try again in {response['data']['retry_after']} seconds.",
            show_alert=True,
        )
        return None

    # Handle errors
    if response["status"] == UpdaterStatus.ERROR.name:
        bot.answer_callback_query(
            call.id,
            text=f"Error checking updates: {response['message']}",
            show_alert=True,
        )
        return None

    # Handle success with no updates
    if not response["data"] or all(
        not image_info["updates"] for image_info in response["data"].values()
    ):
        bot.answer_callback_query(
            call.id,
            text="No updates found for any images.",
            show_alert=True,
        )
        return None

    # Process updates
    prepared_context = prepare_context_for_render(response["data"])

    formatted_context = Compiler.quick_render(
        template_name="d_updates.jinja2", **prepared_context
    )

    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=formatted_context,
        parse_mode="Markdown",
    )
    return None


def prepare_context_for_render(
    data: dict[str, dict[str, list[dict]]],
) -> dict[str, dict[str, dict] | list[str]]:
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
