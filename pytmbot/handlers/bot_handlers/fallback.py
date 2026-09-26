#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import re
from collections.abc import Callable
from typing import Final, cast

from telebot import TeleBot
from telebot.types import Message

from pytmbot.globals import get_session_manager, settings
from pytmbot.handlers.auth_processing.twofa_processing import (
    handle_totp_code_verification,
)
from pytmbot.handlers.handlers_util.utils import send_main_message
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()
session_manager = get_session_manager()

# Near-miss 2FA input such as "12345", "123 456" or "/1234567".
_TOTP_LIKE_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s*/?[\d\s]{1,16}")


def is_unrecognized_private_text(message: Message) -> bool:
    """
    Match text from allowed users in private chats.

    Registered last, after core and plugin handlers, so only text that no other
    handler accepted gets here.
    """
    chat = getattr(message, "chat", None)
    if getattr(chat, "type", None) != "private" or not message.text:
        return False
    user_id = getattr(getattr(message, "from_user", None), "id", None)
    return user_id in settings.access_control.allowed_user_ids


def _is_awaiting_totp_code(message: Message) -> bool:
    user_id = getattr(getattr(message, "from_user", None), "id", None)
    if user_id is None or not _TOTP_LIKE_PATTERN.fullmatch(message.text or ""):
        return False
    return bool(
        session_manager.get_auth_state(user_id)
        == session_manager.state_fabric.PROCESSING
    )


# Registered after plugins so it only sees messages no other handler accepted.
@logger.session_decorator
def handle_unrecognized_message(message: Message, bot: TeleBot) -> None:
    """Reply to unknown text with a short hint and the main menu."""
    if _is_awaiting_totp_code(message):
        # A mistyped code during 2FA gets the 2FA hint, not the generic one.
        verify = cast(Callable[[Message, TeleBot], None], handle_totp_code_verification)
        verify(message, bot)
        return

    response = Compiler.quick_render(template_name="b_echo.jinja2")
    send_main_message(bot, message.chat.id, response)
