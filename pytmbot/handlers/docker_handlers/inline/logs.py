#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from typing import Final

from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot.globals import button_data, em, keyboards, settings
from pytmbot.handlers.handlers_util.docker import get_sanitized_logs, show_handler_info
from pytmbot.logs import Logger
from pytmbot.middleware.session_wrapper import two_factor_auth_required
from pytmbot.parsers.compiler import Compiler
from pytmbot.utils import split_string_into_octets

logger = Logger()

MAX_TELEGRAM_MESSAGE_LENGTH: Final[int] = 4096
LOGS_TRUNCATION_NOTICE: Final[str] = "[LOGS TRUNCATED FOR TELEGRAM LENGTH LIMIT]\n"


def _render_logs_template(
    logs: str, container_name: str, emojis: dict[str, str]
) -> str:
    """Render logs template with provided context."""
    return Compiler.quick_render(
        "d_logs.jinja2", emojis=emojis, logs=logs, container_name=container_name
    )


def _render_logs_with_telegram_limit(
    logs: str, container_name: str, emojis: dict[str, str]
) -> tuple[str, bool]:
    """
    Render logs and ensure resulting Telegram text fits hard 4096-char limit.

    Returns:
        tuple[str, bool]: (rendered_text, was_truncated)
    """
    context = _render_logs_template(logs=logs, container_name=container_name, emojis=emojis)
    if len(context) <= MAX_TELEGRAM_MESSAGE_LENGTH:
        return context, False

    # Keep the newest log lines by taking a tail slice that fits Telegram.
    left, right = 1, len(logs)
    best_context = ""

    while left <= right:
        mid = (left + right) // 2
        tail_logs = logs[-mid:]
        candidate_logs = f"{LOGS_TRUNCATION_NOTICE}{tail_logs}"
        candidate_context = _render_logs_template(
            logs=candidate_logs, container_name=container_name, emojis=emojis
        )

        if len(candidate_context) <= MAX_TELEGRAM_MESSAGE_LENGTH:
            best_context = candidate_context
            left = mid + 1
        else:
            right = mid - 1

    if best_context:
        return best_context, True

    fallback_logs = "Logs are too large to display in Telegram.\nUse server console command below."
    fallback_context = _render_logs_template(
        logs=fallback_logs, container_name=container_name, emojis=emojis
    )

    return fallback_context[:MAX_TELEGRAM_MESSAGE_LENGTH], True


# func=lambda call: call.data.startswith('__get_logs__')
@logger.session_decorator
@two_factor_auth_required
def handle_get_logs(call: CallbackQuery, bot: TeleBot):
    """
    Handles the callback for getting logs of a container.

    Args:
        call (CallbackQuery): The callback query object.
        bot (TeleBot): The Telegram bot object.

    Returns:
        None
    """
    # Extract container name and called user ID from the callback data
    container_name = split_string_into_octets(call.data)
    called_user_id = split_string_into_octets(call.data, octet_index=2)

    # Check if the user is authorized to view logs
    if call.from_user.id not in settings.access_control.allowed_admins_ids or int(
        call.from_user.id
    ) != int(called_user_id):
        logger.warning(
            f"User {call.from_user.id}: Denied '__get_logs__' function for container {container_name}"
        )
        return show_handler_info(
            call=call, text=f"Getting logs for {container_name}: Access denied", bot=bot
        )

    logger.info(
        f"User {call.from_user.id}: Getting logs for container {container_name}"
    )

    # Get logs for the specified container
    logs = get_sanitized_logs(container_name, call, bot.token)

    if not logs:
        logger.error(f"Error getting logs for container {container_name}")
        return show_handler_info(
            call, text=f"{container_name}: Error getting logs", bot=bot
        )

    # Define emojis for rendering
    emojis: dict = {
        "thought_balloon": em.get_emoji("thought_balloon"),
    }

    context, was_truncated = _render_logs_with_telegram_limit(
        logs=logs, container_name=container_name, emojis=emojis
    )

    # Build keyboard buttons
    keyboard_buttons = [
        button_data(
            text=f"{em.get_emoji('BACK_arrow')} Back to {container_name} info",
            callback_data=f"__get_full__:{container_name}:{call.from_user.id}",
        ),
        button_data(
            text=f"{em.get_emoji('house')} Back to all containers",
            callback_data="back_to_containers",
        ),
    ]

    # Build a custom inline keyboard for navigation
    inline_keyboard = keyboards.build_inline_keyboard(keyboard_buttons)

    logger.debug(
        f"Successfully compiled logs for container {container_name}",
        message_length=len(context),
        logs_truncated_for_telegram=was_truncated,
    )

    # Edit the message with the rendered logs and inline keyboard
    return bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=context,
        reply_markup=inline_keyboard,
        parse_mode="HTML",
    )
