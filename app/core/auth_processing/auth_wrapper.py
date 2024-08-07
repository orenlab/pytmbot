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
from app.core.handlers.auth_handlers.auth_required import AuthRequiredHandler, AccessDeniedHandler

authorized_users = []


class AuthorizedUserModel:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.session_expiry = datetime.now() + timedelta(minutes=5)

    def is_session_valid(self) -> bool:
        return datetime.now() < self.session_expiry

    def __post_init__(self):
        self.expiration_time = self.session_expiry + timedelta(minutes=10)


def two_factor_auth_required(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator that enforces two-factor authentication for the provided function.

    Args:
        func: The function to be decorated.

    Returns:
        The wrapper function that enforces two-factor authentication.
    """

    def wrapper(query: Union[Message, CallbackQuery]) -> Any:
        global authorized_users

        user_id = query.from_user.id

        # Check if the user is an allowed admin
        if user_id in config.allowed_admins_ids:
            # Check if the user is not already authorized
            if user_id not in [user.user_id for user in authorized_users]:
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
    # Get the bot instance
    bot_instance = PyTMBotInstance.get_bot_instance()

    # Create an instance of the AuthRequiredHandler
    auth_handler = AuthRequiredHandler(bot_instance)

    return auth_handler.handle_unauthorized_message(query)


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
    # Get the bot instance
    bot_instance = PyTMBotInstance.get_bot_instance()

    # Create an instance of the AccessDeniedHandler
    access_denied_handler = AccessDeniedHandler(bot_instance)

    return access_denied_handler.access_denied_handle(query)
