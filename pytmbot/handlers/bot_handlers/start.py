#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import Message
from telebot.util import extract_arguments, extract_command

from pytmbot import exceptions
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import get_keyboards, get_session_manager, settings
from pytmbot.handlers.auth_processing.auth_processing import (
    PRIVATE_CHAT_START_PAYLOAD,
    handle_unauthorized_message,
    is_private_chat,
)
from pytmbot.handlers.handlers_util.rich_messages import send_rich_main_message
from pytmbot.handlers.handlers_util.utils import send_main_message
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()
keyboards = get_keyboards()
session_manager = get_session_manager()
TWOFA_ALREADY_CONFIRMED_TEXT = (
    "✅ 2FA is already confirmed. Return to the chat and repeat the action."
)


def _twofa_deep_link_admin_id(message: Message) -> int | None:
    """
    Return the admin's user id for ``/start 2fa`` in a private chat, else None.

    Groups link here (``t.me/<bot>?start=2fa``) because 2FA is confirmed only
    in a private chat.
    """
    text = getattr(message, "text", None)
    if not text or message.from_user is None or not is_private_chat(message.chat):
        return None
    is_twofa_link = (
        extract_command(text) == "start"
        and extract_arguments(text) == PRIVATE_CHAT_START_PAYLOAD
    )
    user_id = message.from_user.id
    if is_twofa_link and user_id in settings.access_control.allowed_admins_ids:
        return user_id
    return None


def _handle_twofa_deep_link(message: Message, bot: TeleBot, user_id: int) -> None:
    """Show the 2FA screen, or confirm that 2FA is already done."""
    if session_manager.is_authenticated(user_id):
        send_main_message(bot, message.chat.id, TWOFA_ALREADY_CONFIRMED_TEXT)
        return
    # The action stored in the group stays pending for the "Return" button.
    handle_unauthorized_message(message, bot)


@logger.session_decorator
def handle_start(message: Message, bot: TeleBot) -> None:
    try:
        twofa_admin_id = _twofa_deep_link_admin_id(message)
        if twofa_admin_id is not None:
            _handle_twofa_deep_link(message, bot, twofa_admin_id)
            return

        bot.send_chat_action(message.chat.id, "typing")

        keyboard = keyboards.build_reply_keyboard()

        first_name = (
            message.from_user.first_name if message.from_user else None
        ) or "User"

        answer = Compiler.quick_render(
            template_name="b_index.jinja2", first_name=first_name
        )

        send_rich_main_message(
            bot,
            message.chat.id,
            answer,
            reply_markup=keyboard,
        )

    except Exception as error:
        send_main_message(
            bot,
            message.chat.id,
            "⚠️ Couldn't open the main menu. Please try again.",
        )
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling the start command",
                error_code="HAND_014",
                metadata={"exception": str(error)},
            )
        ) from error
