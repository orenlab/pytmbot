#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import Message

from pytmbot.globals import keyboards, em
from pytmbot.logs import logged_handler_session
from pytmbot.parsers.compiler import Compiler


@logged_handler_session
def handle_navigation(message: Message, bot: TeleBot) -> None:
    """
    Handle navigation in the bot.

    Parameters:
        message (Message): A message object received from the user.
        bot (TeleBot): The bot instance.

    Returns:
        None
    """
    bot.send_chat_action(message.chat.id, "typing")
    main_keyboard = keyboards.build_reply_keyboard()

    first_name: str = message.from_user.first_name

    emojis = {
        "thought_balloon": em.get_emoji("thought_balloon"),
    }

    with Compiler(
        template_name="b_back.jinja2", first_name=first_name, **emojis
    ) as compiler:
        response = compiler.compile()

    # Send the bot answer to the user with the main keyboard
    bot.send_message(message.chat.id, text=response, reply_markup=main_keyboard)
