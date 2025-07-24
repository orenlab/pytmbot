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

        if not processes_data:
            return bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="Sorry, but I can't get process information. Please try again later.",
            )

        # Format table as fixed-width string
        def format_process_table(processes: list[dict], max_name_len: int = 18) -> str:
            from textwrap import shorten

            header = f"{'PID':<6} | {'Process Name':<{max_name_len}} | {'CPU':>5} | {'MEM':>5}"
            separator = "-" * len(header)
            lines = [header, separator]

            for proc in processes:
                pid = str(proc.get("pid", "-"))[:6]
                name = shorten(proc.get("name") or "", width=max_name_len, placeholder="…")
                cpu = f"{proc.get('cpu_percent', 0):>4.1f}%"
                mem = f"{proc.get('memory_percent', 0):>4.1f}%"
                lines.append(f"{pid:<6} | {name:<{max_name_len}} | {cpu:>5} | {mem:>5}")

            return "\n".join(lines)

        context = {
            "process_table": format_process_table(processes_data),
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
