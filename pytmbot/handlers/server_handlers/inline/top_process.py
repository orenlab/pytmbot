#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import datetime

from telebot import TeleBot
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from pytmbot import exceptions
from pytmbot.adapters.psutil.adapter_types import TopProcess
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import (
    get_emoji_converter,
    get_psutil_adapter,
    is_docker_environment,
)
from pytmbot.handlers.server_handlers.cpu import (
    PROCESS_INFO_PREFIX,
    build_cpu_detail_keyboard,
)
from pytmbot.handlers.server_handlers.inline.common import (
    authorize_user_bound_callback,
    edit_callback_message_text,
)
from pytmbot.handlers.server_handlers.process import (
    PROCESS_INFO_FROM_PROCESS_PREFIX,
    PROCESS_OVERVIEW_PREFIX,
    build_process_overview_keyboard,
    render_process_overview_text,
)
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()
em = get_emoji_converter()
psutil_adapter = get_psutil_adapter()
running_in_docker = is_docker_environment()

_PROCESS_INFO_INVALID_PAYLOAD_TEXT = (
    "This button is no longer valid. Please open Process again."
)
_PROCESS_INFO_MISSING_MESSAGE_TEXT = (
    "This message can no longer be updated. Please open Process again."
)


def _is_process_origin_callback(callback_data: str | None) -> bool:
    if callback_data is None:
        return False
    return (
        callback_data == PROCESS_INFO_FROM_PROCESS_PREFIX
        or callback_data.startswith(f"{PROCESS_INFO_FROM_PROCESS_PREFIX}:")
    )


def _authorize_process_info_callback(
    call: CallbackQuery, bot: TeleBot
) -> tuple[bool, int | None, bool]:
    is_process_origin = _is_process_origin_callback(call.data)
    callback_prefix = (
        PROCESS_INFO_FROM_PROCESS_PREFIX if is_process_origin else PROCESS_INFO_PREFIX
    )
    is_allowed, target_user_id = authorize_user_bound_callback(
        call,
        bot,
        prefix=callback_prefix,
        invalid_payload_text=_PROCESS_INFO_INVALID_PAYLOAD_TEXT,
        missing_message_text=_PROCESS_INFO_MISSING_MESSAGE_TEXT,
    )
    return is_allowed, target_user_id, is_process_origin


def _build_process_info_keyboard(
    target_user_id: int | None, *, from_process_command: bool
) -> InlineKeyboardMarkup:
    if from_process_command:
        return build_process_overview_keyboard(
            target_user_id,
            include_back_to_process=True,
        )
    return build_cpu_detail_keyboard(target_user_id, include_back_to_cpu=True)


# func=lambda call: call.data == '__process_info__'
@logger.session_decorator
def handle_process_info(call: CallbackQuery, bot: TeleBot) -> None:
    """Handles the process_info command to display top CPU and memory consuming processes."""
    is_allowed, target_user_id, is_process_origin = _authorize_process_info_callback(
        call, bot
    )
    if not is_allowed:
        return None

    if call.message is None:
        return None

    keyboard = _build_process_info_keyboard(
        target_user_id, from_process_command=is_process_origin
    )

    emojis = {
        "thought_balloon": em.get_emoji("thought_balloon"),
        "information": em.get_emoji("information"),
        "warning": em.get_emoji("warning"),
    }
    fallback_text = (
        "Sorry, I couldn't retrieve process information right now. "
        "Please try again later."
    )

    try:
        processes_data = psutil_adapter.get_top_processes(count=10)

        if not processes_data:
            edit_callback_message_text(
                call,
                bot,
                text=fallback_text,
                reply_markup=keyboard,
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

        edit_callback_message_text(
            call,
            bot,
            text=bot_answer,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
        return None

    except Exception as error:
        edit_callback_message_text(
            call,
            bot,
            text=fallback_text,
            reply_markup=keyboard,
        )
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling inline process info",
                error_code="HAND_010",
                metadata={"exception": str(error)},
            )
        ) from error


@logger.session_decorator
def handle_process_overview(call: CallbackQuery, bot: TeleBot) -> None:
    is_allowed, target_user_id = authorize_user_bound_callback(
        call,
        bot,
        prefix=PROCESS_OVERVIEW_PREFIX,
        invalid_payload_text="This button is no longer valid. Please open Process again.",
        missing_message_text=(
            "This message can no longer be updated. Please open Process again."
        ),
    )
    if not is_allowed:
        return None

    if call.message is None:
        return None

    keyboard = build_process_overview_keyboard(target_user_id)

    try:
        message_text = render_process_overview_text()
        if message_text is None:
            edit_callback_message_text(
                call,
                bot,
                text=(
                    "⚠️ Couldn't retrieve process information right now. "
                    "Please try again later."
                ),
                reply_markup=keyboard,
            )
            return None

        edit_callback_message_text(
            call,
            bot,
            text=message_text,
            parse_mode="HTML",
            reply_markup=keyboard,
        )
        return None
    except Exception as error:
        edit_callback_message_text(
            call,
            bot,
            text="⚠️ An error occurred while processing the command.",
            reply_markup=keyboard,
        )
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling process overview",
                error_code="HAND_011",
                metadata={"exception": str(error)},
            )
        ) from error
