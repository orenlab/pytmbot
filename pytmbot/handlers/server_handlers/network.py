#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, Message

from pytmbot import exceptions
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import (
    ButtonDataType,
    get_emoji_converter,
    get_keyboards,
    get_psutil_adapter,
)
from pytmbot.handlers.server_handlers.inline.common import (
    build_user_bound_callback_data,
)
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()
button_data = ButtonDataType
em = get_emoji_converter()
keyboards = get_keyboards()
psutil_adapter = get_psutil_adapter()

NETWORK_INTERFACES_PREFIX = "__network_interfaces__"
NETWORK_CONNECTIONS_PREFIX = "__network_connections__"
NETWORK_OVERVIEW_PREFIX = "__network_overview__"


def _build_network_keyboard(user_id: int | None) -> InlineKeyboardMarkup:
    buttons = [
        button_data(
            text="Interfaces",
            callback_data=build_user_bound_callback_data(
                NETWORK_INTERFACES_PREFIX, user_id
            ),
        ),
        button_data(
            text="Connections",
            callback_data=build_user_bound_callback_data(
                NETWORK_CONNECTIONS_PREFIX, user_id
            ),
        ),
    ]
    return keyboards.build_inline_keyboard(buttons)


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
        user_id = message.from_user.id if message.from_user is not None else None
        keyboard = _build_network_keyboard(user_id)

        bot.send_message(
            message.chat.id,
            text=message_text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
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
        ) from error
