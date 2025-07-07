#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import Message

from pytmbot import exceptions
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import keyboards, em
from pytmbot.handlers.handlers_util.utils import send_telegram_message
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()


@logger.session_decorator
def handle_navigation(message: Message, bot: TeleBot) -> None:
    """
    Handle navigation in the bot.

    Parameters:
        message (Message): A message object received from the user.
        bot (TeleBot): The bot instance.

    Returns:
        None
    """
    try:
        bot.send_chat_action(message.chat.id, "typing")
        main_keyboard = keyboards.build_reply_keyboard()

        first_name: str = message.from_user.first_name

        emojis = {
            "thought_balloon": em.get_emoji("thought_balloon"),
        }

        with Compiler(
            template_name="b_back.jinja2", first_name=first_name, **emojis
        ) as compiler:
            response = compiler.compile()

        send_telegram_message(
            bot=bot,
            chat_id=message.chat.id,
            text=response,
            reply_markup=main_keyboard,
            parse_mode="HTML",
        )

    except Exception as error:
        bot.send_message(
            message.chat.id, "⚠️ An error occurred while processing the plugins command."
        )
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling the navigation command",
                error_code="HAND_016",
                metadata={"exception": str(error)},
            )
        )
