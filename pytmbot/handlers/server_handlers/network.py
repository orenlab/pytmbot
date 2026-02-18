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

logger = Logger()
em = get_emoji_converter()
psutil_adapter = get_psutil_adapter()


# regexp="Network
@logger.session_decorator
def handle_network(message: Message, bot: TeleBot) -> None:
    emojis = {
        "thought_balloon": em.get_emoji("thought_balloon"),
        "globe_showing_europe_africa": em.get_emoji("globe_showing_Europe-Africa"),
        "hugging_face": em.get_emoji("smiling_face_with_open_hands"),
    }

    try:
        bot.send_chat_action(message.chat.id, "typing")

        network_statistics = psutil_adapter.get_net_io_counters()

        if network_statistics is None:
            logger.error("bot.handler.server.network.get.fail")
            bot.send_message(
                message.chat.id,
                text="⚠️ An error occurred while getting network statistics",
            )
            return None

        message_text = Compiler.quick_render(
            template_name="b_net_io.jinja2", context=network_statistics, **emojis
        )

        bot.send_message(message.chat.id, text=message_text, parse_mode="HTML")
        return None

    except Exception as error:
        bot.send_message(
            message.chat.id, "⚠️ An error occurred while processing the command."
        )
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling network statistics",
                error_code="HAND_005",
                metadata={"exception": str(error)},
            )
        )
