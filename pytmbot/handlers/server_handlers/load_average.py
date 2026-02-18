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
from pytmbot.globals import get_emoji_converter, get_psutil_adapter
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler
from pytmbot.utils import round_up_tuple

logger = Logger()
em = get_emoji_converter()
psutil_adapter = get_psutil_adapter()


# regexp="Load average"
@logger.session_decorator
def handle_load_average(message: Message, bot: TeleBot) -> None:
    emojis = {
        "thought_balloon": em.get_emoji("thought_balloon"),
        "desktop_computer": em.get_emoji("desktop_computer"),
    }

    try:
        bot.send_chat_action(message.chat.id, "typing")

        load_average = round_up_tuple(psutil_adapter.get_load_average())

        if load_average is None:
            logger.error(
                "bot.handler.server.load_average.get.fail"
            )
            bot.send_message(
                message.chat.id, text="⚠️ Some error occurred. Please try again later("
            )
            return None

        # Исправленный вариант - два способа:

        # Способ 1: Статический метод (для trusted templates)
        bot_answer = Compiler.quick_render(
            "b_load_average.jinja2", context=load_average, **emojis
        )

        # Способ 2: Context manager (если нужна валидация)
        # with Compiler("b_load_average.jinja2", trusted=True, context=load_average, **emojis) as compiler:
        #     bot_answer = compiler.compile()

        bot.send_message(message.chat.id, text=bot_answer, parse_mode="Markdown")

    except Exception as error:
        bot.send_message(
            message.chat.id, "⚠️ An error occurred while processing the command."
        )
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling load average",
                error_code="HAND_007",
                metadata={"exception": str(error)},
            )
        )
