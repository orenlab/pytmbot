#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum, auto
from functools import wraps
from typing import Any, Callable, TypeAlias, TypeGuard, Union, cast, TypeVar

import telebot
from telebot.types import Message, CallbackQuery, User

from pytmbot.globals import session_manager, settings
from pytmbot.handlers.auth_processing.auth_processing import (
    handle_unauthorized_message,
    handle_access_denied,
)
from pytmbot.logs import Logger, BaseComponent

logger = Logger()

T = TypeVar("T")

# Type aliases for better readability
TelegramQuery: TypeAlias = Union[Message, CallbackQuery]
HandlerFunction: TypeAlias = Callable[[TelegramQuery, telebot.TeleBot], Any]


class HandlerType(StrEnum):
    """Enum for different types of handlers."""

    CALLBACK_QUERY = auto()
    MESSAGE = auto()


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Data class to store authentication context."""

    user_id: int
    handler_type: HandlerType
    referer_handler: str
    username: str


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
        bool: True if query is valid Message or CallbackQuery
    """
    return isinstance(query, (Message, CallbackQuery))


def get_user_from_query(query: TelegramQuery) -> User | None:
    """
    Safely extract user information from query.

    Args:
        query: Telegram query object

    Returns:
        Optional[User]: User object if available
    """
    return getattr(query, "from_user", None)


def create_auth_context(query: TelegramQuery) -> AuthContext | None:
    """
    Create authentication context from query.

    Args:
        query: Telegram query object

    Returns:
        Optional[AuthContext]: Authentication context if user info is available
    """
    user = get_user_from_query(query)
    if not user:
        return None

    handler_type = (
        HandlerType.CALLBACK_QUERY
        if isinstance(query, CallbackQuery)
        else HandlerType.MESSAGE
    )

    referer_handler = query.data if isinstance(query, CallbackQuery) else query.text

    return AuthContext(
        user_id=user.id,
        handler_type=handler_type,
        referer_handler=str(referer_handler),
        username=user.username or str(user.id),
    )


def handle_unauthorized_query(query: TelegramQuery, bot: telebot.TeleBot) -> None:
    """
    Handle unauthorized queries.

    Args:
        query: The query object
        bot: The bot object
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
    """
    if not is_valid_query(query):
        raise TypeError("Query must be an instance of Message or CallbackQuery")

    with auth_component.log_context(action="access_denied") as log:
        log.warning("Access denied for query")
        return handle_access_denied(query, bot)


def two_factor_auth_required(func: HandlerFunction) -> HandlerFunction:
    """
    Decorator that enforces two-factor authentication.

    Args:
        func: The function to be decorated

    Returns:
        Wrapped function with 2FA check
    """

    @wraps(func)
    @logger.session_decorator
    def wrapper(query: TelegramQuery, bot: telebot.TeleBot) -> Any:
        if not is_valid_query(query):
            raise TypeError("Query must be an instance of Message or CallbackQuery")

        auth_context = create_auth_context(query)
        if not auth_context:
            with auth_component.log_context(action="auth_check") as log:
                log.error("Failed to create auth context: invalid user information")
            return access_denied_handler(query, bot)

        if auth_context.user_id not in settings.access_control.allowed_admins_ids:
            with auth_component.log_context(
                action="auth_check",
                user_id=auth_context.user_id,
                username=auth_context.username,
            ) as log:
                log.warning("User is not in allowed admins list")
            return access_denied_handler(query, bot)

        is_authenticated = session_manager.is_authenticated(auth_context.user_id)

        with auth_component.log_context(
            action="auth_check",
            user_id=auth_context.user_id,
            username=auth_context.username,
            handler_type=auth_context.handler_type.value,
        ) as log:
            log.debug(f"Authentication status: {is_authenticated}")

            if not is_authenticated:
                session_manager.set_referer_data(
                    auth_context.user_id,
                    auth_context.handler_type.value,
                    auth_context.referer_handler,
                )
                log.warning("Authentication required")
                return handle_unauthorized_query(query, bot)

            if session_manager.is_session_expired(auth_context.user_id):
                session_manager.set_auth_state(auth_context.user_id, "unauthenticated")
                log.warning("Session expired")
                return handle_unauthorized_query(query, bot)

            log.success("Access granted")
            return func(query, bot)

    return cast(HandlerFunction, wrapper)
