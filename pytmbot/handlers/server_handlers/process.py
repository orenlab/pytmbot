#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from telebot import TeleBot
from telebot.types import Message

from pytmbot import exceptions
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import em, psutil_adapter, running_in_docker, keyboards, button_data
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()


# regexp="Process")
@logger.session_decorator
def handle_process(message: Message, bot: TeleBot):
    emojis = {
        "thought_balloon": em.get_emoji("thought_balloon"),
        "horizontal_traffic_light": em.get_emoji("horizontal_traffic_light"),
        "warning": em.get_emoji("warning"),
    }

    try:
        bot.send_chat_action(message.chat.id, "typing")

        process_count = psutil_adapter.get_process_counts()

        if process_count is None:
            logger.error(
                f"Failed at @{__name__}: Error occurred while getting process counts"
            )
            return bot.send_message(
                message.chat.id, text="⚠️ Some error occurred. Please try again later("
            )

        inline_key = button_data(
            text="Top 10 processes", callback_data="__process_info__"
        )
        keyboard = keyboards.build_inline_keyboard(inline_key)

        with Compiler(
                template_name="b_process.jinja2",
                context=process_count,
                running_in_docker=running_in_docker,
                **emojis,
        ) as compiler:
            message_text = compiler.compile()

        return bot.send_message(message.chat.id, text=message_text, parse_mode="HTML", reply_markup=keyboard)

    except Exception as error:
        bot.send_message(
            message.chat.id, "⚠️ An error occurred while processing the command."
        )
        raise exceptions.HandlingException(ErrorContext(
            message="Failed handling process",
            error_code="HAND_004",
            metadata={"exception": str(error)}
        ))
