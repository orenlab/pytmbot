#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot.adapters.docker.container_manager import ContainerManager
from pytmbot.adapters.docker.utils import check_container_state
from pytmbot.globals import session_manager, keyboards
from pytmbot.handlers.handlers_util.docker import show_handler_info
from pytmbot.logs import Logger
from pytmbot.middleware.session_wrapper import two_factor_auth_required
from pytmbot.models.docker_models import ContainersState
from pytmbot.utils import split_string_into_octets

logger = Logger()
container_manager = ContainerManager()
containers_state = ContainersState()


def managing_action_fabric(call: CallbackQuery) -> bool:
    """
    Checks if a callback query data starts with a specific action.

    Args:
        call (CallbackQuery): The callback query object.

    Returns:
        bool: True if the callback query data starts with '__start__', '__stop__', or '__restart__',
        False otherwise.
    """
    action = [
        "__start__",
        "__stop__",
        "__restart__",
    ]
    return any(call.data.startswith(callback_data) for callback_data in action)


# func=lambda call: managing_action_fabric(call)
@two_factor_auth_required
@logger.session_decorator
def handle_manage_container_action(call: CallbackQuery, bot: TeleBot):
    """
    Handles the callback query for managing a container.

    Args:
        call (CallbackQuery): The callback query object.
        bot (TeleBot): The Telegram bot object.

    Returns:
        None
    """
    container_name = split_string_into_octets(call.data)
    called_user_id = split_string_into_octets(call.data, octet_index=2)

    if int(call.from_user.id) != int(called_user_id):
        logger.warning(f"User {call.from_user.id}: Denied '__manage__' function")
        return show_handler_info(
            call=call, text=f"Managing {container_name}: Access denied", bot=bot
        )

    if not session_manager.is_authenticated(call.from_user.id):
        logger.warning(
            f"User {call.from_user.id}: Not authenticated. Denied '__manage__' function"
        )
        return show_handler_info(
            call=call,
            text=f"Managing {container_name}: Not authenticated user",
            bot=bot,
        )

    managing_actions = {
        "__start__": __start_container,
        "__stop__": __stop_container,
        "__restart__": __restart_container,
    }
    managing_action = split_string_into_octets(call.data, octet_index=0)

    if managing_action in managing_actions:
        managing_actions[managing_action](
            call=call, container_name=container_name, bot=bot
        )
        return None
    else:
        logger.error(
            f"Error occurred while managing {container_name}: Unknown action {managing_action}"
        )
        return None


def __start_container(call: CallbackQuery, container_name: str, bot: TeleBot):
    """
    Starts a Docker container based on the provided container name and user ID.

    Args:
        call (CallbackQuery): The callback query object containing user information.
        container_name (str): The name of the Docker container to start.
        bot (TeleBot): The Telegram bot object.

    Returns:
        None
    """
    try:
        result = container_manager.managing_container(
            call.from_user.id, container_name, action="start"
        )

        if result is None:
            logger.info(
                f"Starting {container_name} for user {call.from_user.id}: Success"
            )
            return show_handler_info(
                call=call, text=f"Starting {container_name}: Success", bot=bot
            )
        else:
            logger.error(
                f"Starting {container_name} for user {call.from_user.id}: Error occurred"
            )
            return show_handler_info(
                call=call,
                text=f"Starting {container_name}: Error occurred. See logs",
                bot=bot,
            )
    except Exception as e:
        logger.error(f"Error occurred while starting {container_name}: {e}")
        return show_handler_info(
            call=call,
            text=f"Starting {container_name}: Unexpected error occurred",
            bot=bot,
        )


def __stop_container(call: CallbackQuery, container_name: str, bot: TeleBot):
    """
    Stops a Docker container based on the provided container name and user ID.

    Args:
        call (CallbackQuery): The callback query object containing user information.
        container_name (str): The name of the Docker container to stop.
        bot (TeleBot): The Telegram bot object.

    Returns:
        None
    """
    try:
        result = container_manager.managing_container(
            call.from_user.id, container_name, action="stop"
        )

        if result is None:
            logger.info(
                f"Stopping {container_name} for user {call.from_user.id}: Success"
            )
            return show_handler_info(
                call=call, text=f"Stopping {container_name}: Success", bot=bot
            )
        else:
            logger.error(
                f"Stopping {container_name} for user {call.from_user.id}: Error occurred"
            )
            return show_handler_info(
                call=call,
                text=f"Stopping {container_name}: Error occurred. See logs",
                bot=bot,
            )
    except Exception as e:
        logger.error(f"Error occurred while stopping {container_name}: {e}")
        return show_handler_info(
            call=call,
            text=f"Stopping {container_name}: Unexpected error occurred",
            bot=bot,
        )


def __restart_container(call: CallbackQuery, container_name: str, bot: TeleBot):
    """
    Restarts a Docker container based on the provided container name and user ID.

    Args:
        call (CallbackQuery): The callback query object containing user information.
        container_name (str): The name of the Docker container to restart.
        bot (TeleBot): The Telegram bot object.

    Returns:
        None
    """
    try:
        container_manager.managing_container(
            call.from_user.id, container_name, action="restart"
        )
        container_state = check_container_state(container_name)

        if container_state == containers_state.running:
            logger.info(
                f"Restarting {container_name} for user {call.from_user.id}: Success. State: {container_state}"
            )
            keyboards_key = keyboards.ButtonData(
                text=f"Back to {container_name}",
                callback_data=f"__manage__:{container_name}:{call.from_user.id}",
            )
            keyboard = keyboards.build_inline_keyboard(keyboards_key)

            return bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"Restarting {container_name}: Success. State: {container_state}",
                reply_markup=keyboard,
            )
        else:
            logger.error(
                f"Error occurred while restarting {container_name}: State: {container_state}"
            )
            return show_handler_info(
                call=call,
                text=f"Restarting {container_name}: Error occurred. See logs",
                bot=bot,
            )

    except Exception as e:
        logger.error(f"Error occurred while restarting {container_name}: {e}")
        return show_handler_info(
            call=call,
            text=f"Restarting {container_name}: Unexpected error occurred",
            bot=bot,
        )
