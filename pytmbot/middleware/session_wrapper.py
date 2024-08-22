from typing import Union, Callable, Any

import telebot
from telebot.types import Message, CallbackQuery

from pytmbot.globals import session_manager, config
from pytmbot.handlers.auth_processing.auth_processing import handle_unauthorized_message, handle_access_denied
from pytmbot.logs import bot_logger


def handle_unauthorized_query(query: Union[Message, CallbackQuery], bot: telebot.TeleBot) -> bool:
    """
    Handle unauthorized queries.

    Args:
        query (Union[Message, CallbackQuery]): The query object.
        bot (telebot.TeleBot): The bot object.

    Returns:
        bool: True if the query was handled successfully, False otherwise.

    Raises:
        NotImplementedError: If the query type is not supported.
    """
    return handle_unauthorized_message(query, bot)


def access_denied_handler(query: Union[Message, CallbackQuery], bot: telebot.TeleBot) -> bool:
    """
    Handle access denied queries.

    Args:
        query (Union[Message, CallbackQuery]): The query object.
        bot (telebot.TeleBot): The bot object.

    Returns:
        bool: True if the query was handled successfully, False otherwise.

    Raises:
        NotImplementedError: If the query type is not supported.
    """
    return handle_access_denied(query, bot)


def two_factor_auth_required(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator that enforces two-factor authentication for the provided function.

    Args:
        func: The function to be decorated.

    Returns:
        The wrapper function that enforces two-factor authentication.
    """

    def wrapper(query: Union[Message, CallbackQuery], bot: telebot.TeleBot) -> Any:
        user_id = query.from_user.id

        if isinstance(query, CallbackQuery):
            handler_type = 'callback_query'
            referer_handler = query.data
        else:
            handler_type = 'message'
            referer_handler = query.text

        # Check if the user is an allowed admin
        if user_id in config.allowed_admins_ids:
            # Check if the user is not already authorized
            is_user_authenticated = session_manager.is_authenticated(user_id)
            bot_logger.debug(f"User {user_id} is authenticated: {is_user_authenticated}")
            if not is_user_authenticated:
                # Create a new authorized user
                bot_logger.debug(
                    f"Write handler type: {handler_type} and referer handler: {referer_handler} for user {user_id}")
                session_manager.set_referer_uri_and_handler_type_for_user(user_id, handler_type, referer_handler)
                bot_logger.error(f"User {user_id} is not authenticated. Redirecting to the authorization page")
                return handle_unauthorized_query(query, bot)
            elif session_manager.is_session_expired(user_id):
                session_manager.set_auth_state(user_id, 'unauthenticated')
                bot_logger.error(f"Session expired for user {user_id}")
                return handle_unauthorized_query(query, bot)
            else:
                # Log the successful authorization
                bot_logger.debug(f"Administrative access is granted to the user ID {user_id}")

                # Execute the provided function
                return func(query, bot)
        else:
            bot_logger.error(f"Administrative access for users ID {user_id} has been denied")
            return access_denied_handler(query, bot)

    return wrapper
