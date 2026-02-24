#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

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

CPU_INFO_PREFIX = "__cpu_info__"
CPU_PER_CORE_PREFIX = "__cpu_per_core__"
CPU_TIMES_PREFIX = "__cpu_times__"
PROCESS_INFO_PREFIX = "__process_info__"


def _build_cpu_overview_context() -> dict[str, object]:
    cpu_usage = psutil_adapter.get_cpu_usage()
    cpu_freq = psutil_adapter.get_cpu_frequency()
    return {
        "cpu_percent": float(cpu_usage.get("cpu_percent", 0.0)),
        "logical_cores": int(psutil_adapter.get_cpu_count()),
        "physical_cores": int(psutil_adapter.get_cpu_count_physical()),
        "current_freq_mhz": float(cpu_freq.get("current_freq", 0.0)),
        "min_freq_mhz": float(cpu_freq.get("min_freq", 0.0)),
        "max_freq_mhz": float(cpu_freq.get("max_freq", 0.0)),
    }


def _build_cpu_keyboard(user_id: int | None) -> InlineKeyboardMarkup:
    buttons = [
        button_data(
            text="Per-core load",
            callback_data=build_user_bound_callback_data(CPU_PER_CORE_PREFIX, user_id),
        ),
        button_data(
            text="CPU times",
            callback_data=build_user_bound_callback_data(CPU_TIMES_PREFIX, user_id),
        ),
        button_data(
            text="Top 10 processes",
            callback_data=build_user_bound_callback_data(PROCESS_INFO_PREFIX, user_id),
        ),
    ]
    return keyboards.build_inline_keyboard(buttons)


# regexp="CPU"
@logger.session_decorator
def handle_cpu(message: Message, bot: TeleBot) -> None:
    """Handle CPU overview command."""
    try:
        bot.send_chat_action(message.chat.id, "typing")

        cpu_context = _build_cpu_overview_context()
        if not cpu_context:
            logger.error("bot.handler.server.cpu.get.fail")
            bot.send_message(
                message.chat.id, text="⚠️ Failed to get CPU statistics. Try again later."
            )
            return None

        user_id = message.from_user.id if message.from_user is not None else None
        keyboard = _build_cpu_keyboard(user_id)

        cpu_message = Compiler.quick_render(
            template_name="b_cpu.jinja2",
            context=cpu_context,
            running_in_docker=running_in_docker,
            thought_balloon=em.get_emoji("thought_balloon"),
            desktop_computer=em.get_emoji("desktop_computer"),
            warning=em.get_emoji("warning"),
            electric_plug=em.get_emoji("electric_plug"),
        )

        bot.send_message(
            message.chat.id,
            text=cpu_message,
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
                message="Failed handling CPU statistics",
                error_code="HAND_CPU_001",
                metadata={"exception": str(error)},
            )
        )
