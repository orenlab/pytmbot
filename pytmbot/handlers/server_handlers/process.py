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
    is_docker_environment,
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
running_in_docker = is_docker_environment()

PROCESS_INFO_FROM_PROCESS_PREFIX = "__process_info_process__"
PROCESS_OVERVIEW_PREFIX = "__process_overview__"


def _get_process_overview_emojis() -> dict[str, str]:
    return {
        "thought_balloon": em.get_emoji("thought_balloon"),
        "horizontal_traffic_light": em.get_emoji("horizontal_traffic_light"),
        "warning": em.get_emoji("warning"),
    }


def build_process_overview_keyboard(
    user_id: int | None,
    *,
    include_back_to_process: bool = False,
) -> InlineKeyboardMarkup:
    buttons = [
        *(
            [
                button_data(
                    text="Back to Process",
                    callback_data=build_user_bound_callback_data(
                        PROCESS_OVERVIEW_PREFIX, user_id
                    ),
                )
            ]
            if include_back_to_process
            else []
        ),
        button_data(
            text="Top 10 processes",
            callback_data=build_user_bound_callback_data(
                PROCESS_INFO_FROM_PROCESS_PREFIX, user_id
            ),
        ),
    ]
    return keyboards.build_inline_keyboard(buttons)


def render_process_overview_text() -> str | None:
    process_count = psutil_adapter.get_process_counts()
    if process_count is None:
        return None

    return Compiler.quick_render(
        template_name="b_process.jinja2",
        context=process_count,
        running_in_docker=running_in_docker,
        **_get_process_overview_emojis(),
    )


# regexp="Process")
@logger.session_decorator
def handle_process(message: Message, bot: TeleBot) -> None:
    try:
        bot.send_chat_action(message.chat.id, "typing")
        message_text = render_process_overview_text()
        if message_text is None:
            logger.error("bot.handler.server.process.get.fail")
            bot.send_message(
                message.chat.id, text="⚠️ Some error occurred. Please try again later("
            )
            return None

        user_id = message.from_user.id if message.from_user is not None else None
        keyboard = build_process_overview_keyboard(user_id)
        bot.send_message(
            message.chat.id, text=message_text, parse_mode="HTML", reply_markup=keyboard
        )
        return None

    except Exception as error:
        bot.send_message(
            message.chat.id, "⚠️ An error occurred while processing the command."
        )
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling process",
                error_code="HAND_004",
                metadata={"exception": str(error)},
            )
        )
