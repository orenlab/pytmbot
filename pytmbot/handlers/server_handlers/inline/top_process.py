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
from pytmbot.adapters.psutil.adapter_types import TopProcess
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import (
    get_emoji_converter,
    get_psutil_adapter,
    is_docker_environment,
)
from pytmbot.handlers.server_handlers.inline.common import (
    authorize_user_bound_callback,
)
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()
em = get_emoji_converter()
psutil_adapter = get_psutil_adapter()
running_in_docker = is_docker_environment()


# func=lambda call: call.data == '__process_info__'
@logger.session_decorator
def handle_process_info(call: CallbackQuery, bot: TeleBot) -> None:
    """Handles the process_info command to display top CPU and memory consuming processes."""
    is_allowed, _target_user_id = authorize_user_bound_callback(
        call,
        bot,
        prefix="__process_info__",
        invalid_payload_text="Invalid process info request format.",
        missing_message_text="Cannot render process info in this context.",
    )
    if not is_allowed:
        return None

    if call.message is None:
        return None

    emojis = {
        "thought_balloon": em.get_emoji("thought_balloon"),
        "information": em.get_emoji("information"),
        "warning": em.get_emoji("warning"),
    }

    try:
        processes_data = psutil_adapter.get_top_processes(count=10)

        if not processes_data:
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="Sorry, but I can't get process information. Please try again later.",
            )
            return None

        # Format table as fixed-width string
        def format_process_table(
            processes: list[TopProcess], max_name_len: int = 18
        ) -> str:
            from textwrap import shorten

            header = f"{'PID':<6} | {'Process Name':<{max_name_len}} | {'CPU':>5} | {'MEM':>5}"
            separator = "-" * len(header)
            lines = [header, separator]

            for proc in processes:
                pid = str(proc.get("pid", "-"))[:6]
                name = shorten(
                    proc.get("name") or "", width=max_name_len, placeholder="…"
                )
                cpu = f"{proc.get('cpu_percent', 0):>4.1f}%"
                mem = f"{proc.get('memory_percent', 0):>4.1f}%"
                lines.append(f"{pid:<6} | {name:<{max_name_len}} | {cpu:>5} | {mem:>5}")

            return "\n".join(lines)

        context = {
            "process_table": format_process_table(processes_data),
            "running_in_docker": running_in_docker,
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        bot_answer = Compiler.quick_render(
            template_name="b_top_processes.jinja2", context=context, **emojis
        )

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=bot_answer,
            parse_mode="HTML",
        )
        return None

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
