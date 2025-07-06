#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import Message

from pytmbot import exceptions
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import em, psutil_adapter
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()


# regexp="Uptime"
@logger.session_decorator
def handle_uptime(message: Message, bot: TeleBot):
    """
    Handle uptime message from a user.

    Args:
        message (Message): A message object from the user.
        bot (TeleBot): A TeleBot instance.

    Returns:
        None: The function does not return any value. It sends a message to the user with the uptime information.
    """
    emojis = {
        "thought_balloon": em.get_emoji("thought_balloon"),
        "hourglass_not_done": em.get_emoji("hourglass_not_done"),
    }
    try:
        bot.send_chat_action(message.chat.id, "typing")

        uptime_data = psutil_adapter.get_uptime()

        if uptime_data is None:
            logger.error(f"Failed at @{__name__}: Error occurred while getting uptime")
            return bot.send_message(
                message.chat.id, text="⚠️ Some error occurred. Please try again later("
            )

        with Compiler(
            template_name="b_uptime.jinja2", context=uptime_data, **emojis
        ) as compiler:
            bot_answer = compiler.compile()

        return bot.send_message(
            message.chat.id,
            text=bot_answer,
        )

    except Exception as error:
        bot.send_message(
            message.chat.id, "⚠️ An error occurred while processing the command."
        )
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling uptime",
                error_code="HAND_001",
                metadata={"exception": str(error)},
            )
        )
