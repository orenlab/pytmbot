#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from telebot import TeleBot
from telebot.types import Message, LinkPreviewOptions

from pytmbot import exceptions
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import keyboards
from pytmbot.handlers.handlers_util.utils import send_telegram_message
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()


# commands=['help', 'start'])
# @logger.session_decorator
@logger.session_decorator
def handle_start(message: Message, bot: TeleBot) -> None:
    try:
        bot.send_chat_action(message.chat.id, "typing")

        keyboard = keyboards.build_reply_keyboard()

        first_name = message.from_user.first_name

        with Compiler(
                template_name="b_index.jinja2", first_name=first_name
        ) as compiler:
            answer = compiler.compile()

        send_telegram_message(
            bot=bot,
            chat_id=message.chat.id,
            text=answer,
            reply_markup=keyboard,
            parse_mode="Markdown",
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )

    except Exception as error:
        bot.send_message(
            message.chat.id, "⚠️ An error occurred while processing the command."
        )
        raise exceptions.HandlingException(ErrorContext(
            message="Failed handling the start command",
            error_code="HAND_014",
            metadata={"exception": str(error)}
        ))
