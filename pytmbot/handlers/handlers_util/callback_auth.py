#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from telebot.types import CallbackQuery

from pytmbot.globals import get_session_manager, settings

session_manager = get_session_manager()


def parse_callback_target_user(callback_data: str | None, prefix: str) -> int | None:
    """
    Parse callback payload in supported formats:
    - "{prefix}" (legacy, no user binding)
    - "{prefix}:{user_id}" (owner-bound payload)
    """
    if callback_data is None:
        raise ValueError("Callback data is missing")

    if callback_data == prefix:
        return None

    expected_prefix = f"{prefix}:"
    if not callback_data.startswith(expected_prefix):
        raise ValueError("Invalid callback prefix")

    payload = callback_data[len(expected_prefix):].strip()
    if not payload:
        raise ValueError("Missing callback user id")

    try:
        return int(payload)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid callback user id") from exc


def authorize_callback_request(
    call: CallbackQuery,
    *,
    target_user_id: int | None = None,
    require_owner_match: bool = False,
    require_admin: bool = False,
    require_session: bool = False,
) -> tuple[bool, str]:
    """Generic callback authorization guard."""
    if call.from_user is None:
        return False, "Missing user information"

    current_user_id = int(call.from_user.id)

    if current_user_id not in settings.access_control.allowed_user_ids:
        return False, "Access denied"

    if require_admin and current_user_id not in settings.access_control.allowed_admins_ids:
        return False, "Access denied"

    if require_owner_match:
        if target_user_id is None:
            return False, "Invalid target user id"
        if current_user_id != target_user_id:
            return False, "Access denied"

    if require_session and not session_manager.is_authenticated(current_user_id):
        return False, "Not authenticated user"

    return True, ""
