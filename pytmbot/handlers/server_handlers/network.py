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


# regexp="Network
@logger.session_decorator
def handle_network(message: Message, bot: TeleBot):
    emojis = {
        "up_left_arrow": em.get_emoji("up-left_arrow"),
        "up_right_arrow": em.get_emoji("up-right_arrow"),
        "globe_showing_europe_africa": em.get_emoji("globe_showing_Europe-Africa"),
        "hugging_face": em.get_emoji("smiling_face_with_open_hands"),
    }

    try:
        bot.send_chat_action(message.chat.id, "typing")

        network_statistics = psutil_adapter.get_net_io_counters()

        if network_statistics is None:
            logger.error(
                f"Failed at @{__name__}: Error occurred while getting network statistics"
            )
            return bot.send_message(
                message.chat.id,
                text="An error occurred while getting network statistics",
            )

        with Compiler(
                template_name="b_net_io.jinja2", context=network_statistics, **emojis
        ) as compiler:
            message_text = compiler.compile()

        return bot.send_message(
            message.chat.id, text=message_text, parse_mode="Markdown"
        )

    except Exception as error:
        bot.send_message(
            message.chat.id, "⚠️ An error occurred while processing the command."
        )
        raise exceptions.HandlingException(ErrorContext(
            message="Failed handling network statistics",
            error_code="HAND_005",
            metadata={"exception": str(error)}
        ))
