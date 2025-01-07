from typing import Optional

from telebot import TeleBot
from telebot.apihelper import ApiTelegramException
from telebot.types import InlineKeyboardMarkup

from pytmbot import exceptions
from pytmbot.exceptions import ErrorContext
from pytmbot.logs import Logger

logger = Logger()


def send_telegram_message(
        bot: TeleBot,
        chat_id: int,
        text: str,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
        parse_mode: str = "HTML",
        **kwargs
) -> bool:
    """
    Safely sends a message in Telegram with error handling.

    Args:
        bot: TeleBot instance
        chat_id: Chat ID
        text: Message text
        reply_markup: Keyboard markup
        parse_mode: Formatting mode
        **kwargs: Additional keyword arguments

    Returns:
        bool: True if the message was sent successfully

    Raises:
        exceptions.PyTMBotErrorHandlerError: In case of a sending error
    """
    try:
        bot.send_message(
            chat_id,
            text=text if len(text) < 4096 else "Message is too long. I cut it down to 4096 characters: \n\n" + text[
                                                                                                               :4000],
            reply_markup=reply_markup,
            parse_mode=parse_mode,
            **kwargs
        )
        return True

    except ApiTelegramException as e:
        logger.error(
            f"Telegram API error: {e}",
            extra={
                'chat_id': chat_id,
                'text_length': len(text),
                'error': str(e)
            }
        )
        raise exceptions.ConnectionException(ErrorContext(
            message="Telegram API error",
            error_code="TELEGRAM_001",
            metadata={"exception": str(e)}
        ))
