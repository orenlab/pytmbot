#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""


from telebot import TeleBot
from telebot.apihelper import ApiTelegramException
from telebot.types import (
    ForceReply,
    InlineKeyboardMarkup,
    LinkPreviewOptions,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from pytmbot import exceptions
from pytmbot.exceptions import ErrorContext
from pytmbot.logs import Logger

logger = Logger()

type ReplyMarkupType = (
    InlineKeyboardMarkup | ReplyKeyboardMarkup | ForceReply | ReplyKeyboardRemove
)


def send_telegram_message(
    bot: TeleBot,
    chat_id: int,
    text: str,
    reply_markup: ReplyMarkupType | None = None,
    parse_mode: str = "HTML",
    link_preview_options: LinkPreviewOptions | None = None,
    reply_to_message_id: int | None = None,
) -> bool:
    """
    Safely sends a message in Telegram with error handling.

    Args:
        bot: TeleBot instance
        chat_id: Chat ID
        text: Message text
        reply_markup: Keyboard markup
        parse_mode: Formatting mode
        link_preview_options: Optional Telegram link preview settings
        reply_to_message_id: Optional ID of a message to reply to

    Returns:
        bool: True if the message was sent successfully

    Raises:
        exceptions.PyTMBotErrorHandlerError: In case of a sending error
    """
    try:
        bot.send_message(
            chat_id,
            text=(
                text
                if len(text) < 4096
                else "Message is too long. I cut it down to 4096 characters: \n\n"
                + text[:4000]
            ),
            reply_markup=reply_markup,
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
        )
