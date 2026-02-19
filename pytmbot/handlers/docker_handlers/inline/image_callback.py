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
    show_handler_info,
)


def handle_image_details_callback[ParsedT](
    *,
    call: CallbackQuery,
    bot: TeleBot,
    parse_callback: Callable[[str], ParsedT | None],
    extract_user_id: Callable[[ParsedT], int],
    render_callback: Callable[[ParsedT], tuple[str, InlineKeyboardMarkup] | None],
) -> None:
    """Process shared image callback flow (validate, authorize, render, edit)."""
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
            text="Cannot render image details in this context.",
            bot=bot,
        )
        return None

    if call.data is None:
        show_handler_info(
            call=call,
            text="Invalid image details request.",
            bot=bot,
        )
        return None

    parsed = parse_callback(call.data)
    if parsed is None:
        show_handler_info(
            call=call,
            text="Invalid image details request.",
            bot=bot,
        )
        return None

    target_user_id = extract_user_id(parsed)
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

    rendered = render_callback(parsed)
    if rendered is None:
        show_handler_info(
            call=call,
            text="Image details are unavailable. Refresh the images list first.",
            bot=bot,
        )
        return None

    context, inline_keyboard = rendered
    bot.edit_message_text(
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        text=context,
        reply_markup=inline_keyboard,
        parse_mode="HTML",
    )
    return None
