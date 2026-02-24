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

USERS_INFO_PREFIX = "__users_info__"


def _build_uptime_keyboard(user_id: int | None) -> InlineKeyboardMarkup:
    button = button_data(
        text="Active sessions",
        callback_data=build_user_bound_callback_data(USERS_INFO_PREFIX, user_id),
    )
    return keyboards.build_inline_keyboard(button)


# regexp="Uptime"
@logger.session_decorator
def handle_uptime(message: Message, bot: TeleBot) -> None:
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
            logger.error("bot.handler.server.uptime.get.fail")
            bot.send_message(
                message.chat.id, text="⚠️ Some error occurred. Please try again later("
            )
            return None

        bot_answer = Compiler.quick_render(
            template_name="b_uptime.jinja2", context=uptime_data, **emojis
        )
        user_id = message.from_user.id if message.from_user is not None else None
        keyboard = _build_uptime_keyboard(user_id)

        bot.send_message(
            message.chat.id,
            text=bot_answer,
            reply_markup=keyboard,
        )
        return None

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
