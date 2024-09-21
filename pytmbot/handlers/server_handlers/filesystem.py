#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from telebot import TeleBot
from telebot.types import Message

from pytmbot import exceptions
from pytmbot.globals import psutil_adapter, em, running_in_docker
from pytmbot.logs import logged_handler_session, bot_logger
from pytmbot.parsers.compiler import Compiler


# regexp="File system"
@logged_handler_session
def handle_file_system(message: Message, bot: TeleBot):
    try:
        bot.send_chat_action(message.chat.id, "typing")

        disk_usage = psutil_adapter.get_disk_usage()

        if disk_usage is None:
            bot_logger.error("Failed to handle disk usage")
            return bot.send_message(
                message.chat.id,
                text="Failed to handle disk usage. Please try again later.",
            )

        emojis = {
            "thought_balloon": em.get_emoji("thought_balloon"),
            "floppy_disk": em.get_emoji("floppy_disk"),
            "minus": em.get_emoji("minus"),
            "warning": em.get_emoji("warning"),
        }

        with Compiler(
            template_name="b_fs.jinja2",
            context=disk_usage,
            running_in_docker=running_in_docker,
            **emojis,
        ) as compiler:
            bot_answer = compiler.compile()

        return bot.send_message(message.chat.id, text=bot_answer)

    except Exception as error:
        raise exceptions.PyTMBotErrorHandlerError(f"Failed at {__name__}: {error}")
