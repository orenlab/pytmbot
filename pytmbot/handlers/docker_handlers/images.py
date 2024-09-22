#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import Message

from pytmbot import exceptions
from pytmbot.adapters.docker.images_info import fetch_image_details
from pytmbot.globals import keyboards, em
from pytmbot.logs import logged_handler_session, bot_logger
from pytmbot.parsers.compiler import Compiler


# regexp="Images"
# commands=['images']
@logged_handler_session
def handle_images(message: Message, bot: TeleBot):
    """Handle images command."""
    try:
        bot.send_chat_action(message.chat.id, "typing")
        images = fetch_image_details()

        if images is None:
            bot_logger.error(
                f"Failed at @{__name__}: Error occurred while fetching images"
            )
            return bot.send_message(
                message.chat.id, text="Failed to fetch images. Please try again later."
            )

        with Compiler(
            template_name="d_images.jinja2",
            context=images,
            thought_balloon=em.get_emoji("thought_balloon"),
        ) as compiler:
            bot_answer = compiler.compile()

        reply_keyboard = keyboards.build_reply_keyboard(keyboard_type="docker_keyboard")

        return bot.send_message(
            message.chat.id,
            text=bot_answer,
            reply_markup=reply_keyboard,
            parse_mode="HTML",
        )
    except Exception as error:
        raise exceptions.PyTMBotErrorHandlerError(f"Failed at {__name__}: {error}")
