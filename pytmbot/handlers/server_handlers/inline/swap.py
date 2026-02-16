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
from pytmbot.globals import em, psutil_adapter
from pytmbot.handlers.handlers_util.callback_auth import (
    authorize_callback_request,
    parse_callback_target_user,
)
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()


# func=lambda call: call.data == '__swap_info__'
@logger.session_decorator
def handle_swap_info(call: CallbackQuery, bot: TeleBot):
    """Handles the swap_info command."""

    try:
        target_user_id = parse_callback_target_user(call.data, "__swap_info__")
    except ValueError:
        return bot.answer_callback_query(
            callback_query_id=call.id,
            text="Invalid swap request format.",
            show_alert=True,
        )

    is_allowed, deny_reason = authorize_callback_request(
        call,
        target_user_id=target_user_id,
        require_owner_match=target_user_id is not None,
    )
    if not is_allowed:
        return bot.answer_callback_query(
            callback_query_id=call.id,
            text=deny_reason,
            show_alert=True,
        )

    if call.message is None:
        return bot.answer_callback_query(
            callback_query_id=call.id,
            text="Cannot render swap info in this context.",
            show_alert=True,
        )

    emojis = {
        "thought_balloon": em.get_emoji("thought_balloon"),
        "paperclip": em.get_emoji("paperclip"),
    }

    try:
        swap_data = psutil_adapter.get_swap_memory()

        if swap_data is None:
            return bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text="Sorry, but i can't get swap memory values. Please try again later.",
            )

        bot_answer = Compiler.quick_render(
            template_name="b_swap.jinja2", context=swap_data, **emojis
        )

        return bot.edit_message_text(
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            text=bot_answer,
        )
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
