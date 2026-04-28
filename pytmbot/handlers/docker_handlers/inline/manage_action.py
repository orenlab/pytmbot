#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from collections.abc import Callable

from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot.adapters.docker.container_manager import ContainerManager
from pytmbot.globals import ButtonDataType, get_keyboards
from pytmbot.handlers.handlers_util.docker import (
    get_manage_container_callback_context as get_authorized_container_callback_context,
)
from pytmbot.handlers.handlers_util.docker import (
    show_handler_info,
)
from pytmbot.handlers.server_handlers.inline.common import edit_callback_message_text
from pytmbot.logs import Logger
from pytmbot.middleware.session_wrapper import two_factor_auth_required
from pytmbot.utils import split_string_into_octets

logger = Logger()
button_data = ButtonDataType
keyboards = get_keyboards()
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


def _get_manage_action_context(
    call: CallbackQuery, bot: TeleBot
) -> tuple[str, str] | None:
    """Return validated manage-action callback data and container name."""
    context = get_authorized_container_callback_context(
        call=call,
        bot=bot,
        missing_user_event="bot.handler.docker.manage_action.missing.user.warn",
        denied_event="bot.handler.docker.manage_action.denied.manage.deny",
    )
    if context is None:
        return None
    return context.callback_data, context.container_name


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
    callback_context = _get_manage_action_context(call, bot)
    if callback_context is None:
        return
    callback_data, container_name = callback_context

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
    _handle_container_action(
        call=call,
        container_name=container_name,
        bot=bot,
        action="start",
        action_label="Starting",
        success_event="bot.handler.docker.manage_action.user.start.ok",
        error_event="bot.handler.docker.manage_action.start.user.fail",
        unexpected_event="bot.handler.docker.manage_action.start.fail",
    )


def __stop_container(call: CallbackQuery, container_name: str, bot: TeleBot) -> None:
    _handle_container_action(
        call=call,
        container_name=container_name,
        bot=bot,
        action="stop",
        action_label="Stopping",
        success_event="bot.handler.docker.manage_action.user.stop.ok",
        error_event="bot.handler.docker.manage_action.stop.user.fail",
        unexpected_event="bot.handler.docker.manage_action.stop.fail",
    )


def __restart_container(call: CallbackQuery, container_name: str, bot: TeleBot) -> None:
    callback_message = call.message
    if callback_message is None:
        show_handler_info(
            call=call,
            text=f"Restarting {container_name}: Missing callback message",
            bot=bot,
        )
        return

    def _on_restart_success(user_id: int) -> None:
        keyboards_key = button_data(
            text=f"Back to {container_name}",
            callback_data=f"__manage__:{container_name}:{user_id}",
        )
        keyboard = keyboards.build_inline_keyboard(keyboards_key)
        edit_callback_message_text(
            call=call,
            bot=bot,
            text=f"Restarting {container_name}: Success. State: running",
            reply_markup=keyboard,
            not_modified_text=f"Restart result for {container_name} is already shown.",
        )

    _handle_container_action(
        call=call,
        container_name=container_name,
        bot=bot,
        action="restart",
        action_label="Restarting",
        success_event="bot.handler.docker.manage_action.restarting.user.start",
        error_event="bot.handler.docker.manage_action.restart.fail",
        unexpected_event="bot.handler.docker.manage_action.restart.fail",
        on_success=_on_restart_success,
    )


def _handle_container_action(
    call: CallbackQuery,
    container_name: str,
    bot: TeleBot,
    *,
    action: str,
    action_label: str,
    success_event: str,
    error_event: str,
    unexpected_event: str,
    on_success: Callable[[int], None] | None = None,
) -> None:
    """Execute docker action with unified success/error handling."""
    user = call.from_user
    if user is None:
        show_handler_info(
            call=call,
            text=f"{action_label} {container_name}: Missing user information",
            bot=bot,
        )
        return

    try:
        result = container_manager.managing_container(
            user.id, container_name, action=action
        )

        if result is None:
            logger.info(success_event)
            if on_success is not None:
                on_success(user.id)
            else:
                show_handler_info(
                    call=call, text=f"{action_label} {container_name}: Success", bot=bot
                )
            return

        logger.error(error_event)
        show_handler_info(
            call=call,
            text=f"{action_label} {container_name}: Error occurred. See logs",
            bot=bot,
        )
    except Exception:
        logger.error(unexpected_event)
        show_handler_info(
            call=call,
            text=f"{action_label} {container_name}: Unexpected error occurred",
            bot=bot,
        )
