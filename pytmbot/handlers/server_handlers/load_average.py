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
from pytmbot.globals import psutil_adapter, em
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler
from pytmbot.utils.utilities import round_up_tuple

logger = Logger()


# regexp="Load average"
@logger.session_decorator
def handle_load_average(message: Message, bot: TeleBot):
    emojis = {
        "thought_balloon": em.get_emoji("thought_balloon"),
        "desktop_computer": em.get_emoji("desktop_computer"),
    }

    try:
        bot.send_chat_action(message.chat.id, "typing")

        load_average = round_up_tuple(psutil_adapter.get_load_average())

        if load_average is None:
            logger.error(
                f"Failed at @{__name__}: Error occurred while getting load average"
            )
            return bot.send_message(
                message.chat.id, text="Some error occurred. Please try again later("
            )

        with Compiler(
                template_name="b_load_average.jinja2", context=load_average, **emojis
        ) as compiler:
            bot_answer = compiler.compile()

        bot.send_message(message.chat.id, text=bot_answer, parse_mode="Markdown")

    except Exception as error:
        bot.send_message(
            message.chat.id, "⚠️ An error occurred while processing the command."
        )
        raise exceptions.HandlingException(ErrorContext(
            message="Failed handling load average",
            error_code="HAND_007",
            metadata={"exception": str(error)}
        ))
