#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Union, Callable, Any

from telebot.types import Message, CallbackQuery

from app import config, PyTMBotInstance, bot_logger
from app.core.handlers.auth_handlers.auth_required import AuthRequiredHandler

authorized_users = []


@dataclass
class AuthorizedUser:
    """
    Class representing an authorized user. It contains information about the user ID and their login time.

    Attributes:
        user_id (int): The ID of the user.
        login_time (datetime): The time when the user logged in.
        expiration_time (datetime): The time when the user's two-factor authentication expires.
    """
    user_id: int
    login_time: datetime = field(default_factory=datetime.now)
    expiration_time: datetime = field(init=False)
    app_installed: bool = False

    def __post_init__(self):
        self.expiration_time = self.login_time + timedelta(minutes=5)


def two_factor_auth_required(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator that enforces two-factor authentication for the provided function.

    Args:
        func: The function to be decorated.

    Returns:
        The wrapper function that enforces two-factor authentication.
    """

    def wrapper(query: Union[Message, CallbackQuery]) -> Any:
        """
        Wrapper function that performs two-factor authentication before executing the provided function.

        Args:
            query: The query object containing user information.

        Returns:
            The result of the provided function if authentication is successful.
        """
        global authorized_users

        user_id = query.from_user.id

        # Check if the user is an allowed admin
        if user_id in config.allowed_admins_ids:
            # Check if the user is not already authorized
            if user_id not in [user.user_id for user in authorized_users]:
                # Create a new authorized user
                new_authorized_user = AuthorizedUser(user_id=user_id)
                authorized_users.append(new_authorized_user)

                # Remove expired authorized users
                now = datetime.now()
                authorized_users = [user for user in authorized_users if user.expiration_time > now]

                # Log the successful authorization
                bot_logger.debug(f"Administrative access is granted to the user ID {user_id}")

                # Execute the provided function
                return func(query)

        # Log the denied authorization
        bot_logger.error(f"Administrative access for users ID {user_id} has been denied")

        # Return the result of the error_auth_required function
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

    # Check the type of the query
    if isinstance(query, Message):
        # Handle the unauthorized message
        return auth_handler.handle_unauthorized_message(query)
    elif isinstance(query, CallbackQuery):
        # Answer the callback query with a message indicating that the user is not authorized
        return bot_instance.answer_callback_query(
            callback_query_id=query.id,
            text="You are not authorized!",
            show_alert=True
        )
    else:
        # Raise an error for unsupported query types
        raise NotImplementedError("Unsupported query type")
