#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot import exceptions
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import get_emoji_converter, get_psutil_adapter
from pytmbot.handlers.server_handlers.inline.common import (
    authorize_user_bound_callback,
)
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()
em = get_emoji_converter()
psutil_adapter = get_psutil_adapter()


# func=lambda call: call.data == '__swap_info__'
@logger.session_decorator
def handle_swap_info(call: CallbackQuery, bot: TeleBot) -> None:
    """Handles the swap_info command."""

    is_allowed, _target_user_id = authorize_user_bound_callback(
        call,
        bot,
        prefix="__swap_info__",
        invalid_payload_text="Invalid swap request format.",
        missing_message_text="Cannot render swap info in this context.",
    )
    if not is_allowed:
        return None

    if call.message is None:
        return None

    emojis = {
        "thought_balloon": em.get_emoji("thought_balloon"),
        "paperclip": em.get_emoji("paperclip"),
    }

    try:
        swap_data = psutil_adapter.get_swap_memory()

        if swap_data is None:
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="Sorry, but i can't get swap memory values. Please try again later.",
            )
            return None

        bot_answer = Compiler.quick_render(
            template_name="b_swap.jinja2", context=swap_data, **emojis
        )

        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=bot_answer,
        )
        return None
    except Exception as error:
        bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text="Sorry, but i can't get swap memory values. Please try again later.",
        )
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling inline swap info",
                error_code="HAND_009",
                metadata={"exception": str(error)},
            )
        )
