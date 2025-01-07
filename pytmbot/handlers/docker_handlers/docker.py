#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import Message

from pytmbot import exceptions
from pytmbot.adapters.docker.containers_info import fetch_docker_counters
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import keyboards, em
from pytmbot.handlers.handlers_util.utils import send_telegram_message
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()


# regexp="Docker"
# commands="docker"
@logger.session_decorator
def handle_docker(message: Message, bot: TeleBot) -> None:
    try:
        # Send a typing action to indicate that the bot is processing the message
        bot.send_chat_action(message.chat.id, "typing")

        # Compile the message to send to the bot
        bot_answer: str = __compile_message()

        reply_keyboard = keyboards.build_reply_keyboard(keyboard_type="docker_keyboard")

        send_telegram_message(
            bot=bot,
            chat_id=message.chat.id,
            text=bot_answer,
            reply_markup=reply_keyboard,
            parse_mode="HTML",
        )

    except Exception as error:
        bot.send_message(
            message.chat.id, "⚠️ An error occurred while processing the command."
        )
        raise exceptions.HandlingException(ErrorContext(
            message="Failed to handle Docker command",
            error_code="HAND_011",
            metadata={"exception": str(error)}
        ))


def __fetch_counters():
    """
    Fetch Docker counters.

    Returns:
        Optional[Dict[str, int]]: A dictionary containing Docker counters, or None if the counters cannot be
        fetched.
    """
    return fetch_docker_counters()


def __compile_message():
    """
    Compile message and render a bot answer based on docker counters.

    Args:
        : The DockerHandler object.

    Returns:
        dict[str, str] | str | Any: The compiled bot answer based on docker counters or N/A if no counters
        are found.
    """
    docker_counters = __fetch_counters()
    if docker_counters is None:
        return {"images_count": "N/A", "containers_count": "N/A"}

    emojis = {
        "thought_balloon": em.get_emoji("thought_balloon"),
        "spouting_whale": em.get_emoji("spouting_whale"),
        "backhand_index_pointing_down": em.get_emoji("backhand_index_pointing_down"),
    }

    try:
        with Compiler(
                template_name="d_docker.jinja2", context=docker_counters, **emojis
        ) as compiler:
            return compiler.compile()
    except Exception as error:

        raise exceptions.TemplateError(ErrorContext(
            message="Failed to compile Docker template",
            error_code="TEMPL_001",
            metadata={"exception": str(error)}
        ))
