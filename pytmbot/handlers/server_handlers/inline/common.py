#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot.handlers.handlers_util.callback_auth import (
    authorize_callback_request,
    parse_callback_target_user,
)


def build_user_bound_callback_data(prefix: str, user_id: int | None) -> str:
    """Build callback payload with optional owner binding."""
    if user_id is None:
        return prefix
    return f"{prefix}:{user_id}"


def authorize_user_bound_callback(
    call: CallbackQuery,
    bot: TeleBot,
    *,
    prefix: str,
    invalid_payload_text: str,
    missing_message_text: str,
) -> tuple[bool, int | None]:
    """Parse/authorize callback with standard owner-matching semantics."""
    try:
        target_user_id = parse_callback_target_user(call.data or "", prefix)
    except ValueError:
        bot.answer_callback_query(
            callback_query_id=call.id,
            text=invalid_payload_text,
            show_alert=True,
        )
        return False, None

    is_allowed, deny_reason = authorize_callback_request(
        call,
        target_user_id=target_user_id,
        require_owner_match=target_user_id is not None,
    )
    if not is_allowed:
        bot.answer_callback_query(
            callback_query_id=call.id,
            text=deny_reason,
            show_alert=True,
        )
        return False, target_user_id

    if call.message is None:
        bot.answer_callback_query(
            callback_query_id=call.id,
            text=missing_message_text,
            show_alert=True,
        )
        return False, target_user_id

    return True, target_user_id
