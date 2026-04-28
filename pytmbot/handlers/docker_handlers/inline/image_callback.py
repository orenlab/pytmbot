#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from collections.abc import Callable

from telebot import TeleBot
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from pytmbot.handlers.handlers_util.docker import (
    authorize_docker_callback_request,
    get_required_callback_data,
    show_handler_info,
)
from pytmbot.handlers.server_handlers.inline.common import edit_callback_message_text


def handle_image_details_callback[ParsedT](
    *,
    call: CallbackQuery,
    bot: TeleBot,
    parse_callback: Callable[[str], ParsedT | None],
    extract_user_id: Callable[[ParsedT], int],
    render_callback: Callable[[ParsedT], tuple[str, InlineKeyboardMarkup] | None],
) -> None:
    """Process shared image callback flow (validate, authorize, render, edit)."""
    callback_data = get_required_callback_data(
        call=call,
        bot=bot,
        missing_message_text="This image details message can no longer be updated.",
        invalid_button_text="This image details button is no longer valid.",
        alert_handler=show_handler_info,
    )
    if callback_data is None:
        return None

    def reject_request(message_text: str) -> None:
        show_handler_info(call=call, text=message_text, bot=bot)

    parsed = parse_callback(callback_data)
    rejection_text: str | None = None
    target_user_id: int | None = None
    rendered: tuple[str, InlineKeyboardMarkup] | None = None
    if parsed is None:
        rejection_text = "This image details button is no longer valid."
    else:
        target_user_id = extract_user_id(parsed)
        is_allowed, deny_reason = authorize_docker_callback_request(
            call=call,
            called_user_id=target_user_id,
            require_admin=False,
            require_owner_match=True,
            require_session=False,
        )
        if not is_allowed:
            rejection_text = f"Images: {deny_reason}"
        else:
            rendered = render_callback(parsed)
            if rendered is None:
                rejection_text = "Image details are no longer available. Refresh the images list first."

    if rejection_text is not None or rendered is None:
        reject_request(
            rejection_text
            or "Image details are no longer available. Refresh the images list first."
        )
        return None

    context, inline_keyboard = rendered
    edit_callback_message_text(
        call=call,
        bot=bot,
        text=context,
        reply_markup=inline_keyboard,
        parse_mode="HTML",
        not_modified_text="Image details are already current.",
    )
    return None
