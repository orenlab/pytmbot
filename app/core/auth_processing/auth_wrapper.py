#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
import functools
from datetime import datetime, timedelta
from typing import Union, Callable, Any

from telebot.types import Message, CallbackQuery

from app import config, PyTMBotInstance, bot_logger
from app.core.handlers.auth_handlers.auth_required import AuthRequiredHandler
from app.core.handlers.auth_handlers.send_totp_code import TOTPCodeHandler

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

    @functools.wraps(func)
    def wrapper(query: Union[Message, CallbackQuery]) -> Any:
        """
        Wrapper function that performs two-factor authentication before executing the provided function.

        Args:
            query: The query object containing user information.

        Returns:
            The result of the provided function if authentication is successful.
        """
        user_id = query.from_user.id

        if user_id not in config.allowed_admins_ids:
            bot_logger.error(f"Administrative access for users ID {user_id} has been denied")
            return handle_unauthorized_query(query)

        if any(user.user_id == user_id for user in authorized_users if user.is_session_valid()):
            bot_logger.debug(f"Administrative access is granted to the user ID {user_id}")
            return func(query)

        if process_auth(query):
            new_authorized_user = AuthorizedUserModel(user_id=user_id)
            authorized_users.append(new_authorized_user)

            bot_logger.debug(f"Administrative access is granted to the user ID {user_id}")
            return func(query)

        bot_logger.error(f"Administrative access for users ID {user_id} has been denied")
        return handle_unauthorized_query(query)

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


def process_auth(query: Union[Message, CallbackQuery]):
    """
    Process authorized queries.

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
    auth_process_handler = TOTPCodeHandler(bot_instance)

    return auth_process_handler.handle(query)
