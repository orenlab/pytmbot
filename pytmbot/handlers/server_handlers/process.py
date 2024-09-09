#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from telebot import TeleBot
from telebot.types import Message

from pytmbot import exceptions
from pytmbot.globals import em, psutil_adapter
from pytmbot.logs import logged_handler_session, bot_logger
from pytmbot.parsers.compiler import Compiler


# regexp="Process")
@logged_handler_session
def handle_process(message: Message, bot: TeleBot):
    emojis = {
        "thought_balloon": em.get_emoji("thought_balloon"),
        "horizontal_traffic_light": em.get_emoji("horizontal_traffic_light"),
    }

    try:
        bot.send_chat_action(message.chat.id, "typing")

        process_count = psutil_adapter.get_process_counts()

        if process_count is None:
            bot_logger.error(
                f"Failed at @{__name__}: Error occurred while getting process counts"
            )
            return bot.send_message(
                message.chat.id, text="Some error occurred. Please try again later("
            )

        with Compiler(
            template_name="b_process.jinja2", context=process_count, **emojis
        ) as compiler:
            message_text = compiler.compile()

        return bot.send_message(message.chat.id, text=message_text, parse_mode="HTML")

    except Exception as error:
        raise exceptions.PyTMBotErrorHandlerError(f"Failed at {__name__}: {error}")
