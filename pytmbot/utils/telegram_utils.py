#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import re

from telebot.types import CallbackQuery

type OptionalStr = str | None
type OptionalInt = int | None
type OptionalBool = bool | None
type SanitizedLogInput = str | bytes | int | float | bool | None

# Compile regex pattern once for better performance
_ANSI_ESCAPE_PATTERN = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def sanitize_logs(
    container_logs: SanitizedLogInput, callback_query: CallbackQuery, token: str
) -> str:
    """
    Sanitizes container logs by removing ANSI escape sequences
    and masking sensitive user information.

    Args:
        container_logs: Container logs (string or any object with __str__)
        callback_query: Callback query with user information
        token: Bot token to mask

    Returns:
        str: Sanitized logs

    Raises:
        AttributeError: If callback_query doesn't contain required attributes
    """
    # Convert to string if not already a string
    if not isinstance(container_logs, str):
        container_logs = str(container_logs)

    # Remove ANSI escape sequences
    container_logs = _ANSI_ESCAPE_PATTERN.sub("", container_logs)

    # Check for required attributes
    if not (callback_query.from_user and callback_query.message):
        return container_logs

    # Collect sensitive information for masking
    sensitive_info = [
        callback_query.from_user.username or "",
        callback_query.from_user.first_name or "",
        callback_query.from_user.last_name or "",
        str(callback_query.message.from_user.id)
        if callback_query.message.from_user
        else "",
        token,
    ]

    # Filter empty values for better efficiency
    unique_sensitive_info = {
        info for info in sensitive_info if info and info in container_logs
    }
    if not unique_sensitive_info:
        return container_logs

    # Replace all sensitive fragments in a single pass to avoid N string copies.
    pattern = re.compile(
        "|".join(
            re.escape(value)
            for value in sorted(unique_sensitive_info, key=len, reverse=True)
        )
    )
    container_logs = pattern.sub(
        lambda match: "*" * len(match.group(0)), container_logs
    )

    return container_logs
