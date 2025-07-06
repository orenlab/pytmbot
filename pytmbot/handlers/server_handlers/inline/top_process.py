#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import datetime

from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot import exceptions
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import psutil_adapter, em, running_in_docker
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()


# func=lambda call: call.data == '__process_info__'
@logger.session_decorator
def handle_process_info(call: CallbackQuery, bot: TeleBot):
    """Handles the process_info command to display top CPU and memory consuming processes."""

    emojis = {
        "thought_balloon": em.get_emoji("thought_balloon"),
        "information": em.get_emoji("information"),
        "warning": em.get_emoji("warning"),
    }

    try:
        processes_data = psutil_adapter.get_top_processes(count=10)

        if processes_data is None:
            return bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="Sorry, but I can't get process information. Please try again later.",
            )

        context = {
            "processes": processes_data,
            "running_in_docker": running_in_docker,
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        with Compiler(
            template_name="b_top_processes.jinja2", context=context, **emojis
        ) as compiler:
            bot_answer = compiler.compile()

        return bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=bot_answer,
            parse_mode="HTML",
        )

    except Exception as error:
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="Sorry, but I can't get process information. Please try again later.",
        )
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling inline process info",
                error_code="HAND_010",
                metadata={"exception": str(error)},
            )
        )
