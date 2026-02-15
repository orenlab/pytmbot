#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum, auto
from functools import wraps
from typing import Any, Final, TypeAlias, TypeGuard, TypeVar, cast

import telebot
from telebot.types import CallbackQuery, Message, User

from pytmbot.globals import session_manager, settings
from pytmbot.handlers.auth_processing.auth_processing import (
    handle_access_denied,
    handle_unauthorized_message,
)
from pytmbot.logs import BaseComponent, Logger

logger = Logger()

T = TypeVar("T")

# Constants
MAX_USERNAME_LENGTH: Final[int] = 64
MIN_USER_ID: Final[int] = 1

# Type aliases - простые и понятные
TelegramQuery: TypeAlias = Message | CallbackQuery
HandlerFunction: TypeAlias = Callable[[TelegramQuery, telebot.TeleBot], Any]


class HandlerType(StrEnum):
    """Enum for different types of handlers."""

    CALLBACK_QUERY = auto()
    MESSAGE = auto()


class AuthState:
    """Constants for authentication states."""

    AUTHENTICATED: Final[str] = "authenticated"
    UNAUTHENTICATED: Final[str] = "unauthenticated"
    EXPIRED: Final[str] = "expired"


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Data class to store authentication context."""

    user_id: int
    handler_type: HandlerType
    referer_handler: str
    username: str

    def __post_init__(self) -> None:
        """Validate auth context data."""
        if not isinstance(self.user_id, int) or self.user_id < MIN_USER_ID:
            raise ValueError(f"Invalid user_id: {self.user_id}")
        if self.username and len(self.username) > MAX_USERNAME_LENGTH:
            raise ValueError(f"Username too long: {len(self.username)}")


class AuthComponent(BaseComponent):
    """Authentication component with integrated logging."""

    def __init__(self):
        super().__init__("AuthComponent")


auth_component = AuthComponent()


def is_valid_query(query: Any) -> TypeGuard[TelegramQuery]:
    """
    Type guard to validate if the query is of correct type.

    Args:
        query: The query to validate

    Returns:
        bool: True if query is valid Message or CallbackQuery with user info
    """
    return (
            isinstance(query, (Message, CallbackQuery))
            and hasattr(query, 'from_user')
            and query.from_user is not None
    )


def get_user_from_query(query: TelegramQuery) -> User | None:
    """
    Safely extract user information from query.

    Args:
        query: Telegram query object

    Returns:
        User | None: User object if available
    """
    return getattr(query, "from_user", None)


def _determine_handler_type(query: TelegramQuery) -> HandlerType:
    """
    Determine handler type from query object.

    Args:
        query: Telegram query object

    Returns:
        HandlerType: Type of the handler
    """
    return HandlerType.CALLBACK_QUERY if isinstance(query, CallbackQuery) else HandlerType.MESSAGE


def _extract_referer_data(query: TelegramQuery) -> str:
    """
    Extract referer data from query object.

    Args:
        query: Telegram query object

    Returns:
        str: Referer data string
    """
    if isinstance(query, CallbackQuery):
        return str(getattr(query, 'data', '') or '')
    elif isinstance(query, Message):
        return str(getattr(query, 'text', '') or '')
    return ''


def create_auth_context(query: TelegramQuery) -> AuthContext | None:
    """
    Create authentication context from query.

    Args:
        query: Telegram query object

    Returns:
        AuthContext | None: Authentication context if user info is available
    """
    try:
        user = get_user_from_query(query)
        if not user:
            return None

        handler_type = _determine_handler_type(query)
        referer_handler = _extract_referer_data(query)

        return AuthContext(
            user_id=user.id,
            handler_type=handler_type,
            referer_handler=referer_handler,
            username=user.username or str(user.id),
        )
    except (AttributeError, ValueError, TypeError) as e:
        with auth_component.log_context(action="create_auth_context") as log:
            log.error(f"Failed to create auth context: {e}")
        return None


def handle_unauthorized_query(query: TelegramQuery, bot: telebot.TeleBot) -> None:
    """
    Handle unauthorized queries.

    Args:
        query: The query object
        bot: The bot object

    Raises:
        TypeError: If query is not a valid type
    """
    if not is_valid_query(query):
        raise TypeError("Query must be an instance of Message or CallbackQuery")

    with auth_component.log_context(action="handle_unauthorized") as log:
        log.debug("Processing unauthorized query")
        return handle_unauthorized_message(query, bot)


def access_denied_handler(query: TelegramQuery, bot: telebot.TeleBot) -> bool:
    """
    Handle access denied queries.

    Args:
        query: The query object
        bot: The bot object

    Returns:
        bool: True if handled successfully

    Raises:
        TypeError: If query is not a valid type
    """
    if not is_valid_query(query):
        raise TypeError("Query must be an instance of Message or CallbackQuery")

    with auth_component.log_context(action="access_denied") as log:
        log.warning("Access denied for query")
        return handle_access_denied(query, bot)


def _is_user_authorized(user_id: int) -> bool:
    """
    Check if user is in allowed admins list.

    Args:
        user_id: User ID to check

    Returns:
        bool: True if user is authorized
    """
    return user_id in settings.access_control.allowed_admins_ids


def _handle_unauthenticated_user(auth_context: AuthContext, query: TelegramQuery, bot: telebot.TeleBot) -> Any:
    """
    Handle unauthenticated user by setting referer data and redirecting.

    Args:
        auth_context: Authentication context
        query: Telegram query object
        bot: Bot instance

    Returns:
        Result of handle_unauthorized_query
    """
    session_manager.set_referer_data(
        auth_context.user_id,
        auth_context.handler_type.value,
        auth_context.referer_handler,
    )
    return handle_unauthorized_query(query, bot)


def _handle_expired_session(auth_context: AuthContext, query: TelegramQuery, bot: telebot.TeleBot) -> Any:
    """
    Handle expired session by updating state and redirecting.

    Args:
        auth_context: Authentication context
        query: Telegram query object
        bot: Bot instance

    Returns:
        Result of handle_unauthorized_query
    """
    session_manager.set_auth_state(auth_context.user_id, AuthState.UNAUTHENTICATED)
    return handle_unauthorized_query(query, bot)


def two_factor_auth_required(func: HandlerFunction) -> HandlerFunction:
    """
    Decorator that enforces two-factor authentication.

    Args:
        func: The function to be decorated

    Returns:
        HandlerFunction: Wrapped function with 2FA check

    Raises:
        TypeError: If query is not a valid type
    """

    @wraps(func)
    @logger.session_decorator
    def wrapper(query: TelegramQuery, bot: telebot.TeleBot) -> Any:
        if not is_valid_query(query):
            raise TypeError("Query must be an instance of Message or CallbackQuery")

        # Create authentication context
        auth_context = create_auth_context(query)
        if not auth_context:
            with auth_component.log_context(action="auth_check") as log:
                log.error("Failed to create auth context: invalid user information")
            return access_denied_handler(query, bot)

        # Check if user is in allowed admins list
        if not _is_user_authorized(auth_context.user_id):
            with auth_component.log_context(
                    action="auth_check",
                    user_id=auth_context.user_id,
                    username=auth_context.username,
            ) as log:
                log.warning("User is not in allowed admins list")
            return access_denied_handler(query, bot)

        # Check authentication status
        is_authenticated = session_manager.is_authenticated(auth_context.user_id)

        with auth_component.log_context(
                action="auth_check",
        ) as log:
            log.debug(f"Authentication status: {is_authenticated}",
                      context={
                          "user_id": auth_context.user_id,
                          "username": auth_context.username,
                          "handler_type": auth_context.handler_type.value,
                      })

            if not is_authenticated:
                log.warning("Authentication required")
                return _handle_unauthenticated_user(auth_context, query, bot)

            if session_manager.is_session_expired(auth_context.user_id):
                log.warning("Session expired")
                return _handle_expired_session(auth_context, query, bot)

            log.success("Access granted")
            return func(query, bot)

    return cast(HandlerFunction, wrapper)
