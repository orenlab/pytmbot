#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import time
from datetime import datetime
from functools import wraps
from typing import Optional

from telebot import TeleBot
from telebot.apihelper import ApiTelegramException
from telebot.types import Message, InlineKeyboardMarkup

from pytmbot import exceptions
from pytmbot.adapters.docker.images_info import fetch_image_details
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import keyboards, em, button_data
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()


def with_telegram_context(func):
    """
    Decorator to add Telegram-specific context to logging.
    """

    @wraps(func)
    def wrapper(message: Message, bot: TeleBot, *args, **kwargs):
        start_time = time.time()

        # Adding request context
        request_context = {
            'telegram_context': {
                'chat_id': message.chat.id,
                'user_id': message.from_user.id if message.from_user else None,
                'chat_type': message.chat.type,
                'message_id': message.message_id,
                'command': message.text if message.text else None,
                'timestamp': datetime.now().isoformat()
            }
        }

        try:
            logger.debug(
                "Starting Docker images handler",
                extra=request_context
            )

            result = func(message, bot, *args, **kwargs)

            # Adding execution details
            request_context['execution_time'] = f"{time.time() - start_time:.3f}s"
            request_context['success'] = True

            logger.debug(
                "Docker images handler completed successfully",
                extra=request_context
            )

            return result

        except Exception as e:
            request_context.update({
                'execution_time': f"{time.time() - start_time:.3f}s",
                'success': False,
                'error': str(e),
                'error_type': type(e).__name__
            })

            logger.error(
                "Docker images handler failed",
                extra=request_context
            )
            raise

    return wrapper


def send_telegram_message(
        bot: TeleBot,
        chat_id: int,
        text: str,
        reply_markup: Optional[InlineKeyboardMarkup] = None,
        parse_mode: str = "HTML"
) -> bool:
    """
    Safely sends a message in Telegram with error handling.

    Args:
        bot: TeleBot instance
        chat_id: Chat ID
        text: Message text
        reply_markup: Keyboard markup
        parse_mode: Formatting mode

    Returns:
        bool: True if the message was sent successfully

    Raises:
        exceptions.PyTMBotErrorHandlerError: In case of a sending error
    """
    try:
        bot.send_message(
            chat_id,
            text=text[:4096],  # Telegram limit
            reply_markup=reply_markup,
            parse_mode=parse_mode
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

    except Exception as e:
        logger.error(
            f"Failed to send message: {e}",
            extra={
                'chat_id': chat_id,
                'text_length': len(text),
                'error': str(e)
            }
        )
        raise exceptions.HandlingException(ErrorContext(
            message="Failed to send message",
            error_code="TELEGRAM_002",
            metadata={"exception": str(e)}
        ))


@logger.session_decorator
@with_telegram_context
def handle_images(message: Message, bot: TeleBot) -> bool:
    """
    Handler for the 'images' command with enhanced error handling and contextual logging.

    Args:
        message: Incoming Telegram message
        bot: TeleBot instance

    Returns:
        Optional[Message]: Response message or None in case of an error

    Raises:
        exceptions.PyTMBotErrorHandlerError: In case of a command processing error
    """
    global template_context
    try:
        # Send typing action indicator
        bot.send_chat_action(message.chat.id, "typing")

        # Fetch image details
        images = fetch_image_details()
        if images is None:
            logger.error(
                "Failed to fetch Docker images",
                extra={
                    'chat_id': message.chat.id,
                    'error_type': 'ImagesFetchError'
                }
            )
            return send_telegram_message(
                bot,
                message.chat.id,
                "Failed to fetch images. Please try again later."
            )

        # Create a button for checking updates
        keyboard_button = [
            button_data(
                text="Check updates",
                callback_data="__check_updates__"
            )
        ]
        inline_button = keyboards.build_inline_keyboard(keyboard_button)

        # Compile the template
        template_context = {
            'images': images,
            'emojis': {
                'thought_balloon': em.get_emoji("thought_balloon"),
                'spouting_whale': em.get_emoji("spouting_whale"),
                'minus': em.get_emoji("minus")
            }
        }

        with Compiler(
                template_name="d_images.jinja2",
                context=template_context
        ) as compiler:
            bot_answer = compiler.compile()

        # Send the message
        return send_telegram_message(
            bot,
            message.chat.id,
            bot_answer,
            inline_button,
            "HTML"
        )

    except Exception as error:
        bot.send_message(
            message.chat.id, "⚠️ An error occurred while processing the command."
        )
        logger.error(
            f"Images handler error: {error}",
            extra={
                'template_context': template_context,
                'chat_id': message.chat.id,
                'error': str(error),
                'error_type': type(error).__name__
            }
        )
        raise exceptions.HandlingException(ErrorContext(
            message="Images handler error",
            error_code="HAND_010",
            metadata={"exception": str(error)}
        ))
