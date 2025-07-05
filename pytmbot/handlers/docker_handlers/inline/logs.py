#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot.globals import keyboards, em, button_data, settings
from pytmbot.handlers.handlers_util.docker import show_handler_info, get_sanitized_logs
from pytmbot.logs import Logger
from pytmbot.middleware.session_wrapper import two_factor_auth_required
from pytmbot.parsers.compiler import Compiler
from pytmbot.utils import split_string_into_octets

logger = Logger()


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

    with Compiler(
        "d_logs.jinja2", emojis=emojis, logs=logs, container_name=container_name
    ) as compiler:
        context = compiler.compile()

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

    logger.debug(f"Successfully compiled logs for container {container_name}")

    # Edit the message with the rendered logs and inline keyboard
    return bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=context,
        reply_markup=inline_keyboard,
        parse_mode="HTML",
    )
