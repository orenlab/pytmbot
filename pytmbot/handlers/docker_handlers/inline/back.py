#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot.globals import keyboards
from pytmbot.handlers.docker_handlers.containers import get_list_of_containers_again
from pytmbot.logs import logged_inline_handler_session, bot_logger


# func=lambda call: call.data == 'back_to_containers')
@logged_inline_handler_session
def handle_back_to_containers(call: CallbackQuery, bot: TeleBot):
    # Get the updated list of containers and buttons
    context, buttons = get_list_of_containers_again()

    bot_logger.debug(f"Updated list of containers: {buttons}")

    keyboard_buttons = [
        keyboards.ButtonData(text=button.upper(),
                             callback_data=f"__get_full__:{button}:{call.from_user.id}")
        for button in buttons
    ]

    # Build a custom inline keyboard
    inline_keyboard = keyboards.build_inline_keyboard(keyboard_buttons)

    # Edit the message text with the updated container list and keyboard
    return bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=context,
        reply_markup=inline_keyboard,
        parse_mode="HTML"
    )