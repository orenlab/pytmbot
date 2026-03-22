#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from collections.abc import Callable

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

FAN_SPEEDS_PREFIX = "__fan_speeds__"
SENSORS_OVERVIEW_PREFIX = "__sensors_overview__"


def _build_sensors_keyboard(user_id: int | None) -> InlineKeyboardMarkup:
    button = button_data(
        text="Fan speeds",
        callback_data=build_user_bound_callback_data(FAN_SPEEDS_PREFIX, user_id),
    )
    return keyboards.build_inline_keyboard(button)


# regexp="Sensors")
@logger.session_decorator
def handle_sensors(message: Message, bot: TeleBot) -> None:
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
        fan_getter: Callable[[], list[object]] = getattr(
            psutil_adapter, "get_fan_speeds", lambda: []
        )
        fan_speeds = fan_getter()

        if (sensors_data is None or sensors_data == []) and not fan_speeds:
            bot.send_message(
                message.chat.id,
                text="⚠️ No temperature or fan sensors were found.",
            )
            return None

        if sensors_data:
            sensors_message = Compiler.quick_render(
                template_name="b_sensors.jinja2",
                context=sensors_data,
                thought_balloon=em.get_emoji("thought_balloon"),
                thermometer=em.get_emoji("thermometer"),
                exclamation=em.get_emoji("red_exclamation_mark"),
                melting_face=em.get_emoji("melting_face"),
            )
        else:
            sensors_message = (
                f"{em.get_emoji('thought_balloon')} <b>Sensors:</b>\n\n"
                "No temperature sensors are available on this host.\n"
                "Fan speed data is available via the button below."
            )

        keyboard = None
        if fan_speeds:
            user_id = message.from_user.id if message.from_user is not None else None
            keyboard = _build_sensors_keyboard(user_id)

        bot.send_message(
            message.chat.id,
            text=sensors_message,
            parse_mode="HTML",
            reply_markup=keyboard,
        )

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
        ) from error
