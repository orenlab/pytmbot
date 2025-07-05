#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot import exceptions
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import psutil_adapter, em
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()


# func=lambda call: call.data == '__swap_info__'
@logger.session_decorator
def handle_swap_info(call: CallbackQuery, bot: TeleBot):
    """Handles the swap_info command."""

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

        with Compiler(
            template_name="b_swap.jinja2", context=swap_data, **emojis
        ) as compiler:
            bot_answer = compiler.compile()

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
