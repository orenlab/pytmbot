#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from typing import Any

from telebot import TeleBot
from telebot.apihelper import ApiTelegramException
from telebot.types import LinkPreviewOptions, Message

from pytmbot import exceptions
from pytmbot.exceptions import ErrorContext
from pytmbot.keyboards.keyboards import (
    NAV_DOCKER,
    NAV_MAIN,
    NAV_SERVER,
    ReplyMarkupType,
    resolve_reply_markup,
)
from pytmbot.logs import Logger

logger = Logger()


def send_bot_message(
    bot: TeleBot,
    chat_id: int,
    text: str,
    *,
    reply_markup: ReplyMarkupType | None = None,
    nav_keyboard: str | None = None,
    **kwargs: Any,
) -> Message:
    """Send a message, optionally preserving the navigation reply keyboard."""
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
    reply_markup: ReplyMarkupType | None = None,
    parse_mode: str = "HTML",
    link_preview_options: LinkPreviewOptions | None = None,
    reply_to_message_id: int | None = None,
    nav_keyboard: str | None = None,
) -> bool:
    """
    Safely sends a message in Telegram with error handling.

    Args:
        bot: TeleBot instance
        chat_id: Chat ID
        text: Message text
        reply_markup: Keyboard markup
        parse_mode: Formatting mode
        link_preview_options: Telegram link preview settings (LinkPreviewOptions | None)
        reply_to_message_id: ID of a message to reply to (int | None)
        nav_keyboard: Navigation reply keyboard when ``reply_markup`` is omitted

    Returns:
        bool: True if the message was sent successfully

    Raises:
        exceptions.PyTMBotErrorHandlerError: In case of a sending error
    """
    try:
        bot.send_message(
            chat_id=chat_id,
            text=(
                text
                if len(text) < 4096
                else "Message is too long. I cut it down to 4096 characters: \n\n"
                + text[:4000]
            ),
            reply_markup=resolve_reply_markup(reply_markup, nav_keyboard=nav_keyboard),
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
