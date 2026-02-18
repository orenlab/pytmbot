#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot.adapters.docker.client import docker_client_context
from pytmbot.adapters.docker.utils import get_container_state
from pytmbot.globals import ButtonDataType, get_emoji_converter, get_keyboards
from pytmbot.handlers.handlers_util.docker import (
    get_authorized_container_callback_context,
    show_handler_info,
)
from pytmbot.logs import Logger
from pytmbot.middleware.session_wrapper import two_factor_auth_required
from pytmbot.models.docker_models import ContainersState
from pytmbot.parsers.compiler import Compiler

logger = Logger()
button_data = ButtonDataType
em = get_emoji_converter()
keyboards = get_keyboards()
container_state = ContainersState


# func=lambda call: call.data.startswith('__manage__')
@logger.catch()
@logger.session_decorator
@two_factor_auth_required
def handle_manage_container(call: CallbackQuery, bot: TeleBot) -> None:
    """
    Handles the callback for managing a container.

    Args:
        call (CallbackQuery): The callback query object.
        bot (TeleBot): The Telegram bot object.

    Returns:
        None
    """
    auth_context = get_authorized_container_callback_context(
        call=call,
        bot=bot,
        operation_label="Managing",
        missing_user_event="bot.handler.docker.manage.missing.user.warn",
        denied_event="bot.handler.docker.manage.denied.function.deny",
    )
    if auth_context is None:
        return
    container_name = auth_context.container_name

    # Get container state
    with docker_client_context() as adapter:
        state = get_container_state(container_name, docker_client=adapter)
    logger.info("bot.handler.docker.manage.container.state.info")

    # Build keyboard buttons
    keyboard_buttons = []

    # Add action buttons based on container state
    if state == container_state.running:
        logger.debug("bot.handler.docker.manage.adding.stop.debug")
        keyboard_buttons.extend(
            [
                button_data(
                    text=f"{em.get_emoji('no_entry')} Stop",
                    callback_data=f"__stop__:{container_name}:{auth_context.user_id}",
                ),
                button_data(
                    text=f"{em.get_emoji('recycling_symbol')} Restart",
                    callback_data=f"__restart__:{container_name}:{auth_context.user_id}",
                ),
            ]
        )

    elif state in [
        container_state.exited,
        container_state.stopped,
        container_state.dead,
    ]:
        logger.debug("bot.handler.docker.manage.adding.start.debug")
        keyboard_buttons.append(
            button_data(
                text=f"{em.get_emoji('glowing_star')} Start",
                callback_data=f"__start__:{container_name}:{auth_context.user_id}",
            )
        )

    # Always add back button
    keyboard_buttons.append(
        button_data(
            text=f"{em.get_emoji('BACK_arrow')} Back to {container_name} info",
            callback_data=f"__get_full__:{container_name}:{auth_context.user_id}",
        )
    )

    inline_keyboard = keyboards.build_inline_keyboard(keyboard_buttons)

    emojis: dict = {
        "cross_mark": em.get_emoji("cross_mark"),
        "briefcase": em.get_emoji("briefcase"),
        "anxious_face_with_sweat": em.get_emoji("anxious_face_with_sweat"),
        "double_exclamation_mark": em.get_emoji("double_exclamation_mark"),
    }

    rendered_context = Compiler.quick_render(
        "d_managing_containers.jinja2",
        emojis=emojis,
        state=state,
        container_name=container_name,
    )

    callback_message = call.message
    if callback_message is None:
        show_handler_info(
            call=call,
            text=f"Managing {container_name}: Missing callback message",
            bot=bot,
        )
        return

    bot.edit_message_text(
        chat_id=callback_message.chat.id,
        message_id=callback_message.message_id,
        text=rendered_context,
        reply_markup=inline_keyboard,
        parse_mode="HTML",
    )
