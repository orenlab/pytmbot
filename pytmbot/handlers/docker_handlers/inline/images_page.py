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
    get_required_callback_data,
    show_handler_info,
)
from pytmbot.handlers.server_handlers.inline.common import edit_callback_message_text
from pytmbot.logs import Logger

logger = Logger()


@logger.catch()
@logger.session_decorator
def handle_images_page(call: CallbackQuery, bot: TeleBot) -> None:
    callback_data = get_required_callback_data(
        call=call,
        bot=bot,
        missing_message_text="This images list message can no longer be updated.",
        invalid_button_text="This pagination button is no longer valid.",
        alert_handler=show_handler_info,
    )
    if callback_data is None:
        return None

    parsed = parse_page_callback_data(
        callback_data,
        prefix=IMAGES_PAGE_CALLBACK_PREFIX,
    )
    rejection_text: str | None = None
    page = 0
    target_user_id: int | None = None
    if parsed is None:
        rejection_text = "This pagination button is no longer valid."
    else:
        page, target_user_id = parsed
        is_allowed, deny_reason = authorize_docker_callback_request(
            call=call,
            called_user_id=target_user_id,
            require_admin=False,
            require_owner_match=True,
            require_session=False,
        )
        if not is_allowed:
            rejection_text = f"Images: {deny_reason}"

    if rejection_text is not None or target_user_id is None:
        show_handler_info(
            call=call,
            text=rejection_text or "This pagination request is no longer valid.",
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
        not_modified_text="Images list is already current.",
    )
    return None
