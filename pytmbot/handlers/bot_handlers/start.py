#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from telebot import TeleBot
from telebot.types import Message, LinkPreviewOptions

from pytmbot import exceptions
from pytmbot.globals import keyboards
from pytmbot.logs import logged_handler_session
from pytmbot.parsers.compiler import Compiler


# commands=['help', 'start'])
@logged_handler_session
def handle_start(message: Message, bot: TeleBot) -> None:
    try:
        bot.send_chat_action(message.chat.id, "typing")

        keyboard = keyboards.build_reply_keyboard()

        first_name = message.from_user.first_name

        with Compiler(
            template_name="b_index.jinja2", first_name=first_name
        ) as compiler:
            answer = compiler.compile()

        bot.send_message(
            message.chat.id,
            text=answer,
            reply_markup=keyboard,
            parse_mode="Markdown",
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )
    except Exception as error:
        raise exceptions.PyTMBotErrorHandlerError(f"Failed at {__name__}: {error}")
