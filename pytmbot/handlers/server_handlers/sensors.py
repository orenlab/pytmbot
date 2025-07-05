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
from pytmbot.globals import em, psutil_adapter
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()


# regexp="Sensors")
@logger.session_decorator
def handle_sensors(message: Message, bot: TeleBot):
    """
    Handles the "sensors" command.

    Args:
        message (Message): The message object.
        bot (TeleBot): The Telegram bot instance.

    Returns:
        None
    """
    try:
        bot.send_chat_action(message.chat.id, "typing")

        sensors_data = psutil_adapter.get_sensors_temperatures()

        if sensors_data is None or sensors_data == []:
            return bot.send_message(
                message.chat.id,
                text="⚠️ No sensors were found :(",
            )

        with Compiler(
            template_name="b_sensors.jinja2",
            context=sensors_data,
            thought_balloon=em.get_emoji("thought_balloon"),
            thermometer=em.get_emoji("thermometer"),
            exclamation=em.get_emoji("red_exclamation_mark"),
            melting_face=em.get_emoji("melting_face"),
        ) as compiler:
            sensors_message = compiler.compile()

        bot.send_message(message.chat.id, text=sensors_message, parse_mode="HTML")

    except Exception as error:
        bot.send_message(
            message.chat.id, "⚠️ An error occurred while processing the command."
        )
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling sensors",
                error_code="HAND_003",
                metadata={"exception": str(error)},
            )
        )
