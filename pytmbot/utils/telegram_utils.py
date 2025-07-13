#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import re
from typing import Any, Optional, Union

from telebot.types import CallbackQuery, Message

from pytmbot.utils.data_processing import find_in_args, find_in_kwargs

type OptionalStr = Optional[str]
type OptionalInt = Optional[int]
type OptionalBool = Optional[bool]

from typing import NamedTuple


class MessageInfo(NamedTuple):
    """Message information."""

    username: OptionalStr
    user_id: OptionalInt
    language_code: OptionalStr
    is_bot: OptionalBool
    text: OptionalStr


class InlineMessageInfo(NamedTuple):
    """Inline message information."""

    username: OptionalStr
    user_id: OptionalInt
    is_bot: OptionalBool


# Compile regex pattern once for better performance
_ANSI_ESCAPE_PATTERN = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def get_message_full_info(*args: Any, **kwargs: Any) -> MessageInfo:
    """
    Extracts full message information from arguments.

    Args:
        *args: Positional arguments to search for Message object
        **kwargs: Keyword arguments to search for Message object

    Returns:
        MessageInfo: Named tuple with message information
    """
    message = find_in_args(args, Message) or find_in_kwargs(kwargs, Message)
    if message and message.from_user:
        user = message.from_user
        return MessageInfo(
            username=user.username,
            user_id=user.id,
            language_code=user.language_code,
            is_bot=user.is_bot,
            text=message.text,
        )
    return MessageInfo(None, None, None, None, None)


def get_inline_message_full_info(*args: Any, **kwargs: Any) -> InlineMessageInfo:
    """
    Extracts full inline message information from arguments.

    Args:
        *args: Positional arguments to search for CallbackQuery object
        **kwargs: Keyword arguments to search for CallbackQuery object

    Returns:
        InlineMessageInfo: Named tuple with inline message information
    """
    callback_query = find_in_args(args, CallbackQuery) or find_in_kwargs(
        kwargs, CallbackQuery
    )
    if callback_query and callback_query.message and callback_query.message.from_user:
        user = callback_query.message.from_user
        return InlineMessageInfo(
            username=user.username, user_id=user.id, is_bot=user.is_bot
        )
    return InlineMessageInfo(None, None, None)


def sanitize_logs(
    container_logs: Union[str, Any], callback_query: CallbackQuery, token: str
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
    sensitive_info = [info for info in sensitive_info if info]

    # Mask sensitive information
    for sensitive_value in sensitive_info:
        if sensitive_value in container_logs:
            container_logs = container_logs.replace(
                sensitive_value, "*" * len(sensitive_value)
            )

    return container_logs
