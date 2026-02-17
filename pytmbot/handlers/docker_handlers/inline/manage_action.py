#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot.adapters.docker.container_manager import ContainerManager
from pytmbot.globals import button_data, keyboards
from pytmbot.handlers.handlers_util.docker import (
    get_authorized_container_callback_context,
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
    callback_data = call.data or ""
    return any(callback_data.startswith(action_name) for action_name in action)


# func=lambda call: managing_action_fabric(call)
@logger.session_decorator
@two_factor_auth_required
def handle_manage_container_action(call: CallbackQuery, bot: TeleBot) -> None:
    """
    Handles the callback query for managing a container.

    Args:
        call (CallbackQuery): The callback query object.
        bot (TeleBot): The Telegram bot object.

    Returns:
        None
    """
    context = get_authorized_container_callback_context(
        call=call,
        bot=bot,
        operation_label="Managing",
        missing_user_event="bot.handler.docker.manage_action.missing.user.warn",
        denied_event="bot.handler.docker.manage_action.denied.manage.deny",
    )
    if context is None:
        return
    callback_data = context.callback_data
    container_name = context.container_name

    managing_actions = {
        "__start__": __start_container,
        "__stop__": __stop_container,
        "__restart__": __restart_container,
    }
    managing_action = split_string_into_octets(callback_data, octet_index=0)

    if managing_action in managing_actions:
        managing_actions[managing_action](
            call=call, container_name=container_name, bot=bot
        )
        return

    logger.error("bot.handler.docker.manage_action.manage.fail")


def __start_container(call: CallbackQuery, container_name: str, bot: TeleBot) -> None:
    """
    Starts a Docker container based on the provided container name and user ID.

    Args:
        call (CallbackQuery): The callback query object containing user information.
        container_name (str): The name of the Docker container to start.
        bot (TeleBot): The Telegram bot object.

    Returns:
        None
    """
    if call.from_user is None:
        show_handler_info(
            call=call,
            text=f"Starting {container_name}: Missing user information",
            bot=bot,
        )
        return

    try:
        result = container_manager.managing_container(
            call.from_user.id, container_name, action="start"
        )

        if result is None:
            logger.info(
                "bot.handler.docker.manage_action.user.start.ok"
            )
            show_handler_info(
                call=call, text=f"Starting {container_name}: Success", bot=bot
            )
            return
        else:
            logger.error(
                "bot.handler.docker.manage_action.start.user.fail"
            )
            show_handler_info(
                call=call,
                text=f"Starting {container_name}: Error occurred. See logs",
                bot=bot,
            )
            return
    except Exception:
        logger.error("bot.handler.docker.manage_action.start.fail")
        show_handler_info(
            call=call,
            text=f"Starting {container_name}: Unexpected error occurred",
            bot=bot,
        )
        return


def __stop_container(call: CallbackQuery, container_name: str, bot: TeleBot) -> None:
    """
    Stops a Docker container based on the provided container name and user ID.

    Args:
        call (CallbackQuery): The callback query object containing user information.
        container_name (str): The name of the Docker container to stop.
        bot (TeleBot): The Telegram bot object.

    Returns:
        None
    """
    if call.from_user is None:
        show_handler_info(
            call=call,
            text=f"Stopping {container_name}: Missing user information",
            bot=bot,
        )
        return

    try:
        result = container_manager.managing_container(
            call.from_user.id, container_name, action="stop"
        )

        if result is None:
            logger.info(
                "bot.handler.docker.manage_action.user.stop.ok"
            )
            show_handler_info(
                call=call, text=f"Stopping {container_name}: Success", bot=bot
            )
            return
        else:
            logger.error(
                "bot.handler.docker.manage_action.stop.user.fail"
            )
            show_handler_info(
                call=call,
                text=f"Stopping {container_name}: Error occurred. See logs",
                bot=bot,
            )
            return
    except Exception:
        logger.error("bot.handler.docker.manage_action.stop.fail")
        show_handler_info(
            call=call,
            text=f"Stopping {container_name}: Unexpected error occurred",
            bot=bot,
        )
        return


def __restart_container(call: CallbackQuery, container_name: str, bot: TeleBot) -> None:
    """
    Restarts a Docker container based on the provided container name and user ID.

    Args:
        call (CallbackQuery): The callback query object containing user information.
        container_name (str): The name of the Docker container to restart.
        bot (TeleBot): The Telegram bot object.

    Returns:
        None
    """
    if call.from_user is None:
        show_handler_info(
            call=call,
            text=f"Restarting {container_name}: Missing user information",
            bot=bot,
        )
        return

    callback_message = call.message
    if callback_message is None:
        show_handler_info(
            call=call,
            text=f"Restarting {container_name}: Missing callback message",
            bot=bot,
        )
        return

    try:
        result = container_manager.managing_container(
            call.from_user.id, container_name, action="restart"
        )

        if result is None:
            logger.info(
                "bot.handler.docker.manage_action.restarting.user.start"
            )
            keyboards_key = button_data(
                text=f"Back to {container_name}",
                callback_data=f"__manage__:{container_name}:{call.from_user.id}",
            )
            keyboard = keyboards.build_inline_keyboard(keyboards_key)

            bot.edit_message_text(
                chat_id=callback_message.chat.id,
                message_id=callback_message.message_id,
                text=f"Restarting {container_name}: Success. State: running",
                reply_markup=keyboard,
            )
            return

        logger.error(
            "bot.handler.docker.manage_action.restart.fail"
        )
        show_handler_info(
            call=call,
            text=f"Restarting {container_name}: Error occurred. See logs",
            bot=bot,
        )
        return

    except Exception:
        logger.error("bot.handler.docker.manage_action.restart.fail")
        show_handler_info(
            call=call,
            text=f"Restarting {container_name}: Unexpected error occurred",
            bot=bot,
        )
        return
