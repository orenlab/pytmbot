#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from datetime import datetime, timedelta
from typing import Union, Callable, Any

from telebot.types import Message, CallbackQuery

from app import config, PyTMBotInstance, bot_logger
from app.core.handlers.auth_handlers.auth_processing import AuthRequiredHandler, AccessDeniedHandler


def handle_unauthorized_query(query: Union[Message, CallbackQuery]) -> bool:
    """
    Handle unauthorized queries.

    Args:
        query (Union[Message, CallbackQuery]): The query object.

    Returns:
        bool: True if the query was handled successfully, False otherwise.

    Raises:
        NotImplementedError: If the query type is not supported.
    """
    return AuthRequiredHandler(PyTMBotInstance.get_bot_instance()).handle_unauthorized_message(query)


def handle_access_denied(query: Union[Message, CallbackQuery]) -> bool:
    """
    Handle access denied queries.

    Args:
        query (Union[Message, CallbackQuery]): The query object.

    Returns:
        bool: True if the query was handled successfully, False otherwise.

    Raises:
        NotImplementedError: If the query type is not supported.
    """
    return AccessDeniedHandler(PyTMBotInstance.get_bot_instance()).access_denied_handle(query)


_authorized_users = []


class AuthorizedUserModel:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.__session_expiry = datetime.now() + timedelta(minutes=5)

    def is_session_valid(self) -> bool:
        return datetime.now() < self.__session_expiry

    def update_session(self) -> None:
        self.__session_expiry = datetime.now() + timedelta(minutes=5)

    def set_auth_session(self) -> None:
        _authorized_users.append(self)

    def __post_init__(self):
        self.__expiration_time = self.__session_expiry + timedelta(minutes=5)


def two_factor_auth_required(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator that enforces two-factor authentication for the provided function.

    Args:
        func: The function to be decorated.

    Returns:
        The wrapper function that enforces two-factor authentication.
    """

    def wrapper(query: Union[Message, CallbackQuery]) -> Any:

        user_id = query.from_user.id

        # Check if the user is an allowed admin
        if user_id in config.allowed_admins_ids:
            # Check if the user is not already authorized
            if user_id not in [user.user_id for user in _authorized_users]:
                # Create a new authorized user
                return handle_unauthorized_query(query)
            elif not _authorized_users[user_id].is_session_valid():
                # Create a new authorized user
                return handle_unauthorized_query(query)
            else:
                # Log the successful authorization
                bot_logger.debug(f"Administrative access is granted to the user ID {user_id}")

                # Execute the provided function
                return func(query)
        else:
            bot_logger.error(f"Administrative access for users ID {user_id} has been denied")
            return handle_access_denied(query)

    return wrapper
