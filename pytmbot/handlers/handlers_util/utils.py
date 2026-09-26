#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from collections import OrderedDict
from threading import Lock
from typing import Any, Final

from requests import RequestException
from telebot import TeleBot
from telebot.apihelper import ApiTelegramException
from telebot.types import InlineKeyboardMarkup, LinkPreviewOptions, Message

from pytmbot import exceptions
from pytmbot.exceptions import ErrorContext
from pytmbot.keyboards.keyboards import (
    NAV_DOCKER,
    NAV_MAIN,
    NAV_SERVER,
    ReplyMarkupType,
    build_nav_keyboard,
    resolve_reply_markup,
)
from pytmbot.logs import Logger

logger = Logger()

TELEGRAM_MAX_MESSAGE_LENGTH: Final[int] = 4096
HANDLER_COMMAND_ERROR_MESSAGE: Final[str] = (
    "⚠️ Something went wrong. Please try again in a moment."
)
# Sent after inline-keyboard messages so reply keyboards stay visible (notably on iOS).
NAV_KEYBOARD_SYNC_TEXT: Final[str] = "Use the menu below to continue."


def truncate_telegram_text(text: str) -> str:
    """Trim message text to Telegram's maximum message size."""
    if len(text) < TELEGRAM_MAX_MESSAGE_LENGTH:
        return text
    return "Message is too long. I cut it down to 4096 characters: \n\n" + text[:4000]


_MAX_TRACKED_NAV_SYNC_CHATS: Final[int] = 1024
_nav_sync_messages: OrderedDict[int, int] = OrderedDict()
_nav_sync_lock = Lock()


def send_nav_keyboard_sync(bot: TeleBot, chat_id: int, nav_keyboard: str) -> None:
    """
    Re-attach the section reply keyboard with a short follow-up message.

    Only the latest follow-up per chat is kept: the older one is deleted so
    browsing inline screens does not fill the chat with identical notes.

    The follow-up is best effort: the screen itself has already been delivered,
    so a rate limit or network error here is logged instead of raised.
    """
    try:
        sync_message = bot.send_message(
            chat_id=chat_id,
            text=NAV_KEYBOARD_SYNC_TEXT,
            reply_markup=build_nav_keyboard(nav_keyboard),
            disable_notification=True,
        )
    except (ApiTelegramException, RequestException) as error:
        logger.warning(
            "bot.handler.handlers_util.utils.nav.sync.send.fail", error=str(error)
        )
        return
    message_id = getattr(sync_message, "message_id", None)
    if not isinstance(message_id, int):
        return

    with _nav_sync_lock:
        previous_id = _nav_sync_messages.pop(chat_id, None)
        # Concurrent handlers may finish out of order: keep the newest message.
        _nav_sync_messages[chat_id] = max(message_id, previous_id or message_id)
        while len(_nav_sync_messages) > _MAX_TRACKED_NAV_SYNC_CHATS:
            _nav_sync_messages.popitem(last=False)

    if previous_id is None or previous_id == message_id:
        return
    try:
        bot.delete_message(chat_id, min(message_id, previous_id))
    except (ApiTelegramException, RequestException):
        # Already deleted, too old to delete, or a transient network error.
        logger.debug("bot.handler.handlers_util.utils.nav.sync.cleanup.skip")


def send_bot_message(
    bot: TeleBot,
    chat_id: int,
    text: str,
    *,
    reply_markup: ReplyMarkupType | None = None,
    nav_keyboard: str | None = None,
    **kwargs: Any,
) -> Message:
    """
    Send a message, optionally preserving the navigation reply keyboard.

    Telegram allows only one ``reply_markup`` per message. When both an inline
    keyboard and ``nav_keyboard`` are requested, the content message keeps the
    inline actions and a short follow-up re-attaches the section reply keyboard.
    """
    if isinstance(reply_markup, InlineKeyboardMarkup) and nav_keyboard is not None:
        message = bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
            **kwargs,
        )
        send_nav_keyboard_sync(bot, chat_id, nav_keyboard)
        return message

    return bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=resolve_reply_markup(reply_markup, nav_keyboard=nav_keyboard),
        **kwargs,
    )


def send_main_message(
    bot: TeleBot,
    chat_id: int,
    text: str,
    **kwargs: Any,
) -> Message:
    """Send a message while keeping the main menu reply keyboard visible."""
    return send_bot_message(bot, chat_id, text, nav_keyboard=NAV_MAIN, **kwargs)


def send_server_message(
    bot: TeleBot,
    chat_id: int,
    text: str,
    **kwargs: Any,
) -> Message:
    """Send a message while keeping the server section reply keyboard visible."""
    return send_bot_message(bot, chat_id, text, nav_keyboard=NAV_SERVER, **kwargs)


def send_docker_message(
    bot: TeleBot,
    chat_id: int,
    text: str,
    **kwargs: Any,
) -> Message:
    """Send a message while keeping the docker section reply keyboard visible."""
    return send_bot_message(bot, chat_id, text, nav_keyboard=NAV_DOCKER, **kwargs)


def send_telegram_message(
    bot: TeleBot,
    chat_id: int,
    text: str,
    *,
    reply_markup: ReplyMarkupType | None = None,
    parse_mode: str = "HTML",
    link_preview_options: LinkPreviewOptions | None = None,
    reply_to_message_id: int | None = None,
    nav_keyboard: str | None = None,
) -> bool:
    """
    Safely sends a message in Telegram with error handling.

    Returns:
        bool: True if the message was sent successfully

    Raises:
        exceptions.ConnectionException: In case of a Telegram API sending error
    """
    try:
        send_bot_message(
            bot,
            chat_id,
            truncate_telegram_text(text),
            reply_markup=reply_markup,
            nav_keyboard=nav_keyboard,
            parse_mode=parse_mode,
            link_preview_options=link_preview_options,
            reply_to_message_id=reply_to_message_id,
        )
        return True

    except ApiTelegramException as e:
        logger.error(
            "bot.handler.handlers_util.utils.fail",
            extra={"chat_id": chat_id, "text_length": len(text), "error": str(e)},
        )
        raise exceptions.ConnectionException(
            ErrorContext(
                message="Telegram API error",
                error_code="TELEGRAM_001",
                metadata={"exception": str(e)},
            )
        ) from e
