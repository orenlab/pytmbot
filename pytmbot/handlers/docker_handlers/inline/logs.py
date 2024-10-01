#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot.globals import keyboards, em
from pytmbot.handlers.handlers_util.docker import show_handler_info, get_sanitized_logs
from pytmbot.logs import logged_inline_handler_session
from pytmbot.middleware.session_wrapper import two_factor_auth_required
from pytmbot.parsers.compiler import Compiler
from pytmbot.utils.utilities import split_string_into_octets


# func=lambda call: call.data.startswith('__get_logs__')
@logged_inline_handler_session
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
    # Extract container name from the callback data
    container_name = split_string_into_octets(call.data)

    # Get logs for the specified container
    logs = get_sanitized_logs(container_name, call, bot.token)

    if not logs:
        return show_handler_info(
            call, text=f"{container_name}: Error getting logs", bot=bot
        )

    # Define emojis for rendering
    emojis: dict = {
        "thought_balloon": em.get_emoji("thought_balloon"),
    }

    with Compiler(
            "d_logs.jinja2", emojis=emojis, logs=logs, container_name=container_name
    ) as compiler:
        context = compiler.compile()

    keyboard_buttons = keyboards.ButtonData(
        text="Back to all containers", callback_data="back_to_containers"
    )

    # Build a custom inline keyboard for navigation
    inline_keyboard = keyboards.build_inline_keyboard(keyboard_buttons)

    # Edit the message with the rendered logs and inline keyboard
    return bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=context,
        reply_markup=inline_keyboard,
        parse_mode="HTML",
    )
