#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from typing import Final, Tuple, Optional, List, Dict, Any

from telebot import TeleBot
from telebot.types import Message

from pytmbot import exceptions
from pytmbot.adapters.docker.containers_info import retrieve_containers_stats
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import keyboards, em, button_data
from pytmbot.handlers.handlers_util.utils import send_telegram_message
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()


# regexp="Containers"
# commands=["containers"]
@logger.session_decorator
def handle_containers(message: Message, bot: TeleBot) -> None:
    """
    Handle the 'Containers' message by compiling and sending the message to the user or sending an error message.

    Args:
        message (telebot.types.Message): The message object.
        bot (telebot.TeleBot): The bot object.

    Returns:
        None
    """
    try:
        bot.send_chat_action(message.chat.id, "typing")

        containers_info = __compile_message()

        inline_keyboard = (
            keyboards.build_inline_keyboard(
                [
                    button_data(
                        text=name,
                        callback_data=f"__get_full__:{name.lower()}:{message.from_user.id}",
                    )
                    for name in containers_info[1]
                ]
            )
            if containers_info[1]
            else None
        )

        send_telegram_message(
            bot=bot,
            chat_id=message.chat.id,
            text=containers_info[0],
            reply_markup=inline_keyboard,
            parse_mode="HTML",
        )

    except Exception as error:
        bot.send_message(
            message.chat.id, "⚠️ An error occurred while processing the command."
        )
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling containers",
                error_code="HAND_012",
                metadata={"exception": str(error)},
            )
        )


def __get_container_data() -> list[dict[str, str]] | dict[None, None] | dict[Any, Any]:
    """
    Retrieves the container data using the DockerAdapter.

    Returns:
        dict: A dictionary containing the container data or None if an error occurs.

    Raises:
        Exception: If an error occurs during the retrieval process.
    """
    try:
        return retrieve_containers_stats()
    except Exception as e:
        raise exceptions.DockerOperationException(
            ErrorContext(
                message="Failed to retrieve container data",
                error_code="DOCKER_001",
                metadata={"exception": str(e)},
            )
        )


def __compile_message() -> Tuple[str, Optional[List[str]]]:
    """
    Compiles the message using the DockerAdapter.

    Returns:
        tuple: A tuple containing the compiled message and a list of container names.

    Raises:
        Exception: If an error occurs during the compilation process.
    """
    try:
        container_data = __get_container_data()

        if not container_data or container_data == [{}]:
            template_name: Final[str] = "b_none.jinja2"

            # Define context and emojis
            context: Final[str] = (
                "There are no containers or incorrect settings are specified."
            )
            emojis: Final[Dict[str, str]] = {
                "thought_balloon": em.get_emoji("thought_balloon"),
            }

            containers_name = None
        else:
            template_name: Final[str] = "d_containers.jinja2"

            context: Dict = container_data
            containers_name = [container.get("name") for container in context]

            emojis: Final[Dict[str, str]] = {
                "thought_balloon": em.get_emoji("thought_balloon"),
                "oil_drum": em.get_emoji("oil_drum"),
                "id": em.get_emoji("ID_button"),
                "package": em.get_emoji("package"),
                "mantelpiece_clock": em.get_emoji("mantelpiece_clock"),
                "rocket": em.get_emoji("rocket"),
                "antenna_bars": em.get_emoji("antenna_bars"),
                "magnifying_glass": em.get_emoji("magnifying_glass_tilted_left"),
            }

        # Render the template with the context data and emojis
        with Compiler(
            template_name=template_name, context=context, **emojis
        ) as compiler:
            compiled_data = compiler.compile()

        return compiled_data, containers_name

    except Exception as e:
        raise exceptions.TemplateError(
            ErrorContext(
                message="Failed to compile message",
                error_code="TEMPL_001",
                metadata={"exception": str(e)},
            )
        )


def get_list_of_containers_again() -> Tuple[str, Optional[List[str]]]:
    """
    Returns the list of containers again.

    Returns:
        tuple[str, List[str] | None]: The compiled message to be sent to the bot and a list of container names
            if available, or None if no container data is available.
    """
    return __compile_message()
