#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import re

from telebot import TeleBot
from telebot.apihelper import ApiTelegramException
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from pytmbot.handlers.handlers_util.callback_auth import (
    authorize_callback_request,
    parse_callback_target_user,
)

_RETRY_AFTER_PATTERN = re.compile(r"retry after\s+(\d+)", re.IGNORECASE)


def _extract_retry_after_seconds(error: ApiTelegramException) -> int | None:
    retry_after_raw = getattr(error, "retry_after", None)
    if isinstance(retry_after_raw, (int, float)):
        retry_after = int(retry_after_raw)
        return retry_after if retry_after > 0 else None

    result_json = getattr(error, "result_json", None)
    if isinstance(result_json, dict):
        parameters = result_json.get("parameters")
        if isinstance(parameters, dict):
            retry_after_obj = parameters.get("retry_after")
            if isinstance(retry_after_obj, (int, float)):
                retry_after = int(retry_after_obj)
                return retry_after if retry_after > 0 else None

    error_description = getattr(error, "description", str(error))
    if isinstance(error_description, str):
        match = _RETRY_AFTER_PATTERN.search(error_description)
        if match:
            try:
                retry_after = int(match.group(1))
            except ValueError:
                return None
            return retry_after if retry_after > 0 else None

    return None


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


def edit_callback_message_text(
    call: CallbackQuery,
    bot: TeleBot,
    *,
    text: str,
    parse_mode: str | None = None,
    reply_markup: InlineKeyboardMarkup | None = None,
    not_modified_text: str = "View is already up to date.",
) -> bool:
    """Edit callback-bound message and treat Telegram 'not modified' as a no-op."""
    if call.message is None:
        return False

    try:
        if parse_mode is not None and reply_markup is not None:
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=text,
                parse_mode=parse_mode,
                reply_markup=reply_markup,
            )
        elif parse_mode is not None:
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=text,
                parse_mode=parse_mode,
            )
        elif reply_markup is not None:
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=text,
                reply_markup=reply_markup,
            )
        else:
            bot.edit_message_text(
                chat_id=call.message.chat.id,
                message_id=call.message.message_id,
                text=text,
            )
        return True
    except ApiTelegramException as error:
        if getattr(error, "error_code", None) == 429:
            retry_after = _extract_retry_after_seconds(error)
            if getattr(call, "id", None) is not None:
                callback_text = (
                    "Telegram API is rate limited. Try again shortly."
                    if retry_after is None
                    else f"Telegram API is rate limited. Try again in {retry_after}s."
                )
                bot.answer_callback_query(
                    callback_query_id=call.id,
                    text=callback_text,
                    show_alert=False,
                )
            return False

        error_description = getattr(error, "description", str(error))
        is_not_modified = (
            getattr(error, "error_code", None) == 400
            and "message is not modified" in str(error_description).lower()
        )
        if not is_not_modified:
            raise

        if getattr(call, "id", None) is not None:
            bot.answer_callback_query(
                callback_query_id=call.id,
                text=not_modified_text,
                show_alert=False,
            )
        return False
