#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot.handlers.docker_handlers.containers import (
    CONTAINERS_PAGE_CALLBACK_PREFIX,
    get_list_of_containers_again,
)
from pytmbot.handlers.docker_handlers.pagination import parse_page_callback_data
from pytmbot.handlers.handlers_util.docker import (
    authorize_docker_callback_request,
    show_handler_info,
)
from pytmbot.handlers.server_handlers.inline.common import edit_callback_message_text
from pytmbot.logs import Logger

logger = Logger()


def _parse_back_callback_data(callback_data: str) -> tuple[int, int | None]:
    """
    Parse callback for containers list navigation.

    Supported payloads:
    - 'back_to_containers' -> first page for current user
    - '__containers_page__:{page}:{user_id}'
    """
    if callback_data == "back_to_containers":
        return 1, None

    parsed = parse_page_callback_data(
        callback_data,
        prefix=CONTAINERS_PAGE_CALLBACK_PREFIX,
    )
    if parsed is None:
        raise ValueError("Invalid containers pagination callback format")

    page, user_id = parsed
    return page, user_id


# func=lambda call: call.data == 'back_to_containers')
@logger.session_decorator
def handle_back_to_containers(call: CallbackQuery, bot: TeleBot) -> None:
    if call.from_user is None:
        show_handler_info(
            call=call,
            text="Cannot identify callback user.",
            bot=bot,
        )
        return None

    if call.message is None:
        show_handler_info(
            call=call,
            text="Cannot refresh containers list in this context.",
            bot=bot,
        )
        return None

    if call.data is None:
        show_handler_info(
            call=call,
            text="Invalid containers pagination request.",
            bot=bot,
        )
        return None

    try:
        page, callback_user_id = _parse_back_callback_data(call.data)
    except ValueError as exc:
        logger.warning("bot.handler.docker.back.parse.containers.fail", error=str(exc))
        show_handler_info(
            call=call,
            text="Invalid containers pagination request.",
            bot=bot,
        )
        return None

    current_user_id = int(call.from_user.id)
    target_user_id = (
        callback_user_id if callback_user_id is not None else current_user_id
    )

    is_allowed, deny_reason = authorize_docker_callback_request(
        call=call,
        called_user_id=target_user_id,
        require_admin=False,
        require_owner_match=callback_user_id is not None,
        require_session=False,
    )
    if not is_allowed:
        show_handler_info(
            call=call,
            text=f"Containers: {deny_reason}",
            bot=bot,
        )
        return None

    context, inline_keyboard = get_list_of_containers_again(
        page=page,
        user_id=target_user_id,
    )

    logger.debug(
        "bot.handler.docker.back.updated.list.debug",
        page=page,
        user_id=target_user_id,
    )

    edit_callback_message_text(
        call=call,
        bot=bot,
        text=context,
        reply_markup=inline_keyboard,
        parse_mode="HTML",
        not_modified_text="Containers list is already up to date.",
    )
    return None
