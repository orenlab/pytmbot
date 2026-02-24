#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot.handlers.docker_handlers.images import (
    IMAGES_PAGE_CALLBACK_PREFIX,
    render_images_page,
)
from pytmbot.handlers.docker_handlers.pagination import parse_page_callback_data
from pytmbot.handlers.handlers_util.docker import (
    authorize_docker_callback_request,
    show_handler_info,
)
from pytmbot.handlers.server_handlers.inline.common import edit_callback_message_text
from pytmbot.logs import Logger

logger = Logger()


@logger.catch()
@logger.session_decorator
def handle_images_page(call: CallbackQuery, bot: TeleBot) -> None:
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
            text="Cannot update images list in this context.",
            bot=bot,
        )
        return None

    if call.data is None:
        show_handler_info(
            call=call,
            text="Invalid images pagination request.",
            bot=bot,
        )
        return None

    parsed = parse_page_callback_data(
        call.data,
        prefix=IMAGES_PAGE_CALLBACK_PREFIX,
    )
    if parsed is None:
        show_handler_info(
            call=call,
            text="Invalid images pagination request.",
            bot=bot,
        )
        return None

    page, target_user_id = parsed
    is_allowed, deny_reason = authorize_docker_callback_request(
        call=call,
        called_user_id=target_user_id,
        require_admin=False,
        require_owner_match=True,
        require_session=False,
    )
    if not is_allowed:
        show_handler_info(
            call=call,
            text=f"Images: {deny_reason}",
            bot=bot,
        )
        return None

    context, inline_keyboard = render_images_page(page=page, user_id=target_user_id)

    edit_callback_message_text(
        call=call,
        bot=bot,
        text=context,
        reply_markup=inline_keyboard,
        parse_mode="HTML",
        not_modified_text="Images list is already up to date.",
    )
    return None
