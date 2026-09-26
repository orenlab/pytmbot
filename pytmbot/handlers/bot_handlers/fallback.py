#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import Message

from pytmbot.handlers.handlers_util.utils import send_main_message
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()


def is_unrecognized_private_text(message: Message) -> bool:
    """Match text in private chats; registered last, after core and plugin handlers."""
    chat = getattr(message, "chat", None)
    return getattr(chat, "type", None) == "private" and bool(message.text)


# Registered after plugins so it only sees messages no other handler accepted.
@logger.session_decorator
def handle_unrecognized_message(message: Message, bot: TeleBot) -> None:
    """Reply to unknown text with a short hint and the main menu."""
    response = Compiler.quick_render(template_name="b_echo.jinja2")
    send_main_message(bot, message.chat.id, response)
