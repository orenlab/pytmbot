#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import Message, LinkPreviewOptions

from pytmbot import exceptions
from pytmbot.exceptions import ErrorContext
from pytmbot.handlers.handlers_util.utils import send_telegram_message
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()


# commands=['getmyid', 'id'])
@logger.session_decorator
def handle_getmyid(message: Message, bot: TeleBot) -> None:
    """
    Handler for /getmyid command - returns user and chat ID information
    for initial bot configuration and debugging purposes.
    """
    try:
        bot.send_chat_action(message.chat.id, "typing")

        # Extract user and chat information
        user_id = message.from_user.id
        chat_id = message.chat.id
        first_name = message.from_user.first_name or "Unknown"
        last_name = message.from_user.last_name or ""
        username = message.from_user.username
        chat_type = message.chat.type
        chat_title = getattr(message.chat, "title", None)

        # Map chat type to readable format
        chat_type_display = {
            "private": "Private Chat",
            "group": "Group",
            "supergroup": "Supergroup",
            "channel": "Channel",
        }.get(chat_type, chat_type.title())

        # Determine if user is bot admin (if applicable)
        is_bot_admin = message.from_user.id in getattr(bot, "admin_ids", [])

        with Compiler(
            template_name="b_getmyid.jinja2",
            user_id=user_id,
            chat_id=chat_id,
            first_name=first_name,
            last_name=last_name,
            username=username,
            chat_type=chat_type_display,
            chat_title=chat_title,
            command="getmyid",
            is_bot_admin=is_bot_admin,
        ) as compiler:
            answer = compiler.compile()

        send_telegram_message(
            bot=bot,
            chat_id=message.chat.id,
            text=answer,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )

    except Exception as error:
        bot.send_message(
            message.chat.id, "⚠️ An error occurred while retrieving ID information."
        )
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling the getmyid command",
                error_code="HAND_015",
                metadata={
                    "exception": str(error),
                    "user_id": message.from_user.id if message.from_user else None,
                    "chat_id": message.chat.id if message.chat else None,
                    "command": "getmyid",
                },
            )
        )
