#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot.adapters.docker.container_manager import ContainerManager
from pytmbot.globals import keyboards
from pytmbot.handlers.handlers_util.docker import (
    authorize_docker_callback_request,
    show_handler_info,
)
from pytmbot.logs import Logger
from pytmbot.middleware.session_wrapper import two_factor_auth_required
from pytmbot.utils import split_string_into_octets

logger = Logger()
container_manager = ContainerManager()


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

    if call.from_user is None:
        logger.warning(
            "bot.handler.docker.manage_action.missing.user.warn", callback_data=call.data
        )
        return show_handler_info(
            call=call,
            text=f"Managing {container_name}: Missing user information",
            bot=bot,
        )

    is_allowed, deny_reason = authorize_docker_callback_request(call, called_user_id)
    if not is_allowed:
        logger.warning(
            "bot.handler.docker.manage_action.denied.manage.deny",
            user_id=call.from_user.id,
            container_name=container_name,
            reason=deny_reason,
        )
        return show_handler_info(
            call=call,
            text=f"Managing {container_name}: {deny_reason}",
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
            "bot.handler.docker.manage_action.manage.fail"
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
                "bot.handler.docker.manage_action.user.start.ok"
            )
            return show_handler_info(
                call=call, text=f"Starting {container_name}: Success", bot=bot
            )
        else:
            logger.error(
                "bot.handler.docker.manage_action.start.user.fail"
            )
            return show_handler_info(
                call=call,
                text=f"Starting {container_name}: Error occurred. See logs",
                bot=bot,
            )
    except Exception:
        logger.error("bot.handler.docker.manage_action.start.fail")
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
                "bot.handler.docker.manage_action.user.stop.ok"
            )
            return show_handler_info(
                call=call, text=f"Stopping {container_name}: Success", bot=bot
            )
        else:
            logger.error(
                "bot.handler.docker.manage_action.stop.user.fail"
            )
            return show_handler_info(
                call=call,
                text=f"Stopping {container_name}: Error occurred. See logs",
                bot=bot,
            )
    except Exception:
        logger.error("bot.handler.docker.manage_action.stop.fail")
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
        result = container_manager.managing_container(
            call.from_user.id, container_name, action="restart"
        )

        if result is None:
            logger.info(
                "bot.handler.docker.manage_action.restarting.user.start"
            )
            keyboards_key = keyboards.ButtonData(
                text=f"Back to {container_name}",
                callback_data=f"__manage__:{container_name}:{call.from_user.id}",
            )
            keyboard = keyboards.build_inline_keyboard(keyboards_key)

            return bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=f"Restarting {container_name}: Success. State: running",
                reply_markup=keyboard,
            )

        logger.error(
            "bot.handler.docker.manage_action.restart.fail"
        )
        return show_handler_info(
            call=call,
            text=f"Restarting {container_name}: Error occurred. See logs",
            bot=bot,
        )

    except Exception:
        logger.error("bot.handler.docker.manage_action.restart.fail")
        return show_handler_info(
            call=call,
            text=f"Restarting {container_name}: Unexpected error occurred",
            bot=bot,
        )
