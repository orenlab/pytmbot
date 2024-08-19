#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from telebot import TeleBot
from telebot.types import Message

from pytmbot import exceptions
from pytmbot.globals import em
from pytmbot.logs import logged_handler_session
from pytmbot.parsers.compiler import Compiler


# func=lambda message: True
@logged_handler_session
def handle_echo(message: Message, bot: TeleBot):
    """
    Handles the 'echo' command.

    Args:
        message (Message): The message object received from the user.
        bot (TeleBot): The TeleBot instance.

    Returns:
        Message: The message object sent by the bot.

    Raises:
        PyTMBotErrorHandlerError: If there is a ValueError while rendering the templates.
    """
    try:
        bot.send_chat_action(message.chat.id, 'typing')
        emojis: dict = {
            'thought_balloon': em.get_emoji('thought_balloon'),
        }

        with Compiler(template_name='b_echo.jinja2', first_name=message.from_user.first_name, **emojis) as compiler:
            bot_answer = compiler.compile()

        return bot.send_message(message.chat.id, text=bot_answer)

    except Exception as error:
        raise exceptions.PyTMBotErrorHandlerError(f"Failed at {__name__}: {error}")
