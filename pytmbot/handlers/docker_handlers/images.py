#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from typing import Optional

from telebot import TeleBot
from telebot.types import Message

from pytmbot import exceptions
from pytmbot.adapters.docker.images_info import fetch_image_details
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import keyboards, em, button_data
from pytmbot.handlers.handlers_util.utils import send_telegram_message
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()


@logger.session_decorator
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

    template_context = None

    try:

        # Send typing action indicator
        bot.send_chat_action(message.chat.id, "typing")

        # Fetch image details
        images = fetch_image_details()
        if images is None:
            logger.error(
                "Failed to fetch Docker images",
                extra={"chat_id": message.chat.id, "error_type": "ImagesFetchError"},
            )
            return send_telegram_message(
                bot, message.chat.id, "Failed to fetch images. Please try again later."
            )

        # Create a button for checking updates
        keyboard_button = [
            button_data(text="Check updates", callback_data="__check_updates__")
        ]
        inline_button = keyboards.build_inline_keyboard(keyboard_button)

        # Compile the template
        template_context = {
            "images": images,
            "emojis": {
                "thought_balloon": em.get_emoji("thought_balloon"),
                "spouting_whale": em.get_emoji("spouting_whale"),
                "minus": em.get_emoji("minus"),
                "package": em.get_emoji("package"),
                "bookmark_tabs": em.get_emoji("bookmark_tabs"),
                "gear": em.get_emoji("gear"),
                "desktop_computer": em.get_emoji("desktop_computer"),
                "floppy_disk": em.get_emoji("floppy_disk"),
                "mantelpiece_clock": em.get_emoji("mantelpiece_clock"),
                "person_technologist": em.get_emoji("person_technologist"),
                "wrench": em.get_emoji("wrench"),
                "label": em.get_emoji("label"),
                "electric_plug": em.get_emoji("electric_plug"),
                "key": em.get_emoji("key"),
                "arrow_right": em.get_emoji("arrow_right"),
                "computer_mouse": em.get_emoji("computer_mouse"),
            },
        }

        with Compiler(
            template_name="d_images.jinja2", context=template_context
        ) as compiler:
            bot_answer = compiler.compile()

        # Send the message
        return send_telegram_message(
            bot, message.chat.id, bot_answer, inline_button, "HTML"
        )

    except Exception as error:
        bot.send_message(
            message.chat.id, "⚠️ An error occurred while processing the command."
        )
        logger.error(
            f"Images handler error: {error}",
            extra={
                "template_context": template_context,
                "chat_id": message.chat.id,
                "error": str(error),
                "error_type": type(error).__name__,
            },
        )
        raise exceptions.HandlingException(
            ErrorContext(
                message="Images handler error",
                error_code="HAND_010",
                metadata={"exception": str(error)},
            )
        )
