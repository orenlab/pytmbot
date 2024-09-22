#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from telebot import TeleBot
from telebot.types import Message

from pytmbot import exceptions
from pytmbot.adapters.docker.containers_info import retrieve_containers_stats
from pytmbot.globals import keyboards, em
from pytmbot.logs import bot_logger, logged_handler_session
from pytmbot.parsers.compiler import Compiler


# regexp="Containers"
# commands=["containers"]
@logged_handler_session
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

        keyboard_keys = [
            keyboards.ButtonData(
                text=name,
                callback_data=f"__get_full__:{name.lower()}:{message.from_user.id}",
            )
            for name in containers_info[1]
        ]

        inline_keyboard = keyboards.build_inline_keyboard(keyboard_keys)

        # Send the message to the user
        bot.send_message(
            message.chat.id,
            text=containers_info[0],
            reply_markup=inline_keyboard if keyboard_keys else None,
            parse_mode="HTML",
        )

    except Exception as error:
        raise exceptions.PyTMBotErrorHandlerError(f"Failed at {__name__}: {error}")


def __get_container_data():
    """
    Retrieves the container data using the DockerAdapter.

    Returns:
        dict: A dictionary containing the container data.

    Raises:
        Exception: If an error occurs during the retrieval process.
    """
    try:
        return retrieve_containers_stats()
    except Exception as e:
        bot_logger.error(f"Failed at {__name__}: {e}")
        return {}


def __compile_message():
    """
    Compiles the message using the DockerAdapter.

    Returns:
        tuple: A tuple containing the compiled message and a list of container names.

    Raises:
        Exception: If an error occurs during the compilation process.
    """
    try:
        container_data = __get_container_data()

        if not container_data:
            template_name: str = "b_none.jinja2"

            # Define context and emojis
            context: str = (
                "There are no containers or incorrect settings are specified."
            )
            emojis: dict = {
                "thought_balloon": em.get_emoji("thought_balloon"),
            }

            containers_name = None
        else:
            template_name: str = "d_containers.jinja2"

            context: dict = container_data

            containers_name = [container.get("name") for container in context]

            emojis: dict = {
                "thought_balloon": em.get_emoji("thought_balloon"),
                "luggage": em.get_emoji("pushpin"),
                "minus": em.get_emoji("minus"),
            }

        # Render the template with the context data and emojis
        with Compiler(
            template_name=template_name, context=context, **emojis
        ) as compiler:
            compiled_data = compiler.compile()

        return compiled_data, containers_name

    except Exception as e:
        bot_logger.error(f"Failed at {__name__}: {e}")


def get_list_of_containers_again():
    """
    Returns the list of containers again.

    Returns:
        tuple[str, List[str] | None]: The compiled message to be sent to the bot and a list of container names
            if available, or None if no container data is available.
    """
    return __compile_message()
