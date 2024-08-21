#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot.globals import keyboards, em, session_manager
from pytmbot.handlers.handlers_util.docker import show_handler_info
from pytmbot.logs import logged_inline_handler_session, bot_logger
from pytmbot.middleware.session_wrapper import two_factor_auth_required
from pytmbot.parsers.compiler import Compiler
from pytmbot.utils.utilities import split_string_into_octets


# func=lambda call: call.data.startswith('__manage__')
@bot_logger.catch()
@two_factor_auth_required
@logged_inline_handler_session
def handle_manage_container(call: CallbackQuery, bot: TeleBot):
    """
    Handles the callback for managing a container.

    Args:
        call (CallbackQuery): The callback query object.
        bot (TeleBot): The Telegram bot object.

    Returns:
        None
    """
    # Extract container name and called user ID from the callback data
    container_name = split_string_into_octets(call.data)
    called_user_id = split_string_into_octets(call.data, octet_index=2)

    # Check if the user is an admin
    if int(call.from_user.id) != int(called_user_id):
        bot_logger.log("DENIED", f"User {call.from_user.id} NOT is an admin. Denied '__manage__' function")
        return show_handler_info(call=call, text=f"Managing {container_name}: Access denied", bot=bot)

    is_authenticated = session_manager.is_authenticated(call.from_user.id)
    bot_logger.debug(f"User {call.from_user.id} authenticated status: {is_authenticated}")

    if not is_authenticated:
        bot_logger.log("DENIED",
                       f"User {call.from_user.id} NOT authenticated. "
                       f"Denied '__manage__' function for container {container_name}")
        return show_handler_info(call=call, text=f"Managing {container_name}: Not authenticated user", bot=bot)

    # Create the keyboard buttons
    keyboard_buttons = [
        keyboards.ButtonData(text="Start",
                             callback_data=f'__start__:{container_name}:{call.from_user.id}'),
        keyboards.ButtonData(text="Stop",
                             callback_data=f'__stop__:{container_name}:{call.from_user.id}'),
        keyboards.ButtonData(text="Restart",
                             callback_data=f'__restart__:{container_name}:{call.from_user.id}'),
        keyboards.ButtonData(text="Rename",
                             callback_data=f'__rename__:{container_name}:{call.from_user.id}'),
    ]

    inline_keyboard = keyboards.build_inline_keyboard(keyboard_buttons)

    emojis: dict = {
        'thought_balloon': em.get_emoji('thought_balloon'),
    }

    with Compiler(
            'd_managing_containers.jinja2',
            emojis=emojis,
            container_name=container_name
    ) as compiler:
        context = compiler.compile()

    return bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=context,
        reply_markup=inline_keyboard
    )
