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

DISK_IO_PREFIX = "__disk_io__"
FILESYSTEM_OVERVIEW_PREFIX = "__filesystem_overview__"


def _build_filesystem_keyboard(user_id: int | None) -> InlineKeyboardMarkup:
    button = button_data(
        text="I/O stats",
        callback_data=build_user_bound_callback_data(DISK_IO_PREFIX, user_id),
    )
    return keyboards.build_inline_keyboard(button)


# regexp="File system"
@logger.session_decorator
def handle_file_system(message: Message, bot: TeleBot) -> None:
    try:
        bot.send_chat_action(message.chat.id, "typing")

        disk_usage = psutil_adapter.get_disk_usage()

        if disk_usage is None:
            logger.error("bot.handler.server.filesystem.disk.usage.fail")
            bot.send_message(
                message.chat.id,
                text="⚠️ Failed to handle disk usage. Please try again later.",
            )
            return None

        emojis = {
            "thought_balloon": em.get_emoji("thought_balloon"),
            "floppy_disk": em.get_emoji("floppy_disk"),
            "minus": em.get_emoji("minus"),
            "warning": em.get_emoji("warning"),
        }

        bot_answer = Compiler.quick_render(
            template_name="b_fs.jinja2",
            context=disk_usage,
            running_in_docker=running_in_docker,
            **emojis,
        )
        user_id = message.from_user.id if message.from_user is not None else None
        keyboard = _build_filesystem_keyboard(user_id)

        bot.send_message(
            message.chat.id,
            text=bot_answer,
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
                message="Failed handling disk usage",
                error_code="HAND_008",
                metadata={"exception": str(error)},
            )
        )
