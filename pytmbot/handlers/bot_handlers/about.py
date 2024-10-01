#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import Message, LinkPreviewOptions

from pytmbot import exceptions
from pytmbot.globals import __version__
from pytmbot.logs import logged_handler_session
from pytmbot.parsers.compiler import Compiler


@logged_handler_session
def handle_about_command(message: Message, bot: TeleBot) -> None:
    """
    Handles the 'About' command received by the bot.

    Parameters:
        message (Message): The message object containing the 'About' command.
        bot (TeleBot): The bot instance that received the message.

    Returns:
        None
    """
    try:
        user_name = (
            message.from_user.first_name
            if message.from_user.first_name
            else message.from_user.username
        )
        bot.send_chat_action(message.chat.id, "typing")

        template_data = {"username": user_name, "app_version": __version__}

        with Compiler(
                template_name="b_about_bot.jinja2", context=template_data
        ) as compiler:
            response = compiler.compile()

        bot.send_message(
            message.chat.id,
            text=response,
            parse_mode="Markdown",
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )

    except Exception as error:
        raise exceptions.PyTMBotErrorHandlerError(f"Failed at {__name__}: {error}")
