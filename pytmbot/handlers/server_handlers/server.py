#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import Message

from pytmbot import exceptions
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import keyboards, em
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()


@logger.session_decorator
def handle_server(message: Message, bot: TeleBot) -> None:
    """
    Handle navigation in the bot.

    Parameters:
        message (Message): A message object received from the user.
        bot (TeleBot): The bot instance.

    Returns:
        None
    """
    try:
        bot.send_chat_action(message.chat.id, "typing")
        server_keyboard = keyboards.build_reply_keyboard(keyboard_type="server_keyboard")

        first_name: str = message.from_user.first_name

        emojis = {
            "thought_balloon": em.get_emoji("thought_balloon"),
        }

        with Compiler(
                template_name="b_server.jinja2", first_name=first_name, **emojis
        ) as compiler:
            response = compiler.compile()

        bot.send_message(
            message.chat.id,
            text=response,
            reply_markup=server_keyboard,
            parse_mode="Markdown",
        )
    except Exception as error:
        bot.send_message(
            message.chat.id, "⚠️ An error occurred while processing the command."
        )
        raise exceptions.HandlingException(ErrorContext(
            message="Failed handling server command",
            error_code="HAND_002",
            metadata={"exception": str(error)}
        ))
