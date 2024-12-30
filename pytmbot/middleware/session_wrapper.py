from typing import Union, Callable, Any

import telebot
from telebot.types import Message, CallbackQuery

from pytmbot.globals import session_manager, settings
from pytmbot.handlers.auth_processing.auth_processing import (
    handle_unauthorized_message,
    handle_access_denied,
)
from pytmbot.logs import bot_logger


def handle_unauthorized_query(
    query: Union[Message, CallbackQuery], bot: telebot.TeleBot
) -> None:
    """
    Handle unauthorized queries.

    Args:
        query (Union[Message, CallbackQuery]): The query object.
        bot (telebot.TeleBot): The bot object.

    Returns:
        bool: True if the query was handled successfully, False otherwise.
    """
    if not isinstance(query, (Message, CallbackQuery)):
        raise TypeError("Query must be an instance of Message or CallbackQuery")
    return handle_unauthorized_message(query, bot)


def access_denied_handler(
    query: Union[Message, CallbackQuery], bot: telebot.TeleBot
) -> bool:
    """
    Handle access denied queries.

    Args:
        query (Union[Message, CallbackQuery]): The query object.
        bot (telebot.TeleBot): The bot object.

    Returns:
        bool: True if the query was handled successfully, False otherwise.
    """
    if not isinstance(query, (Message, CallbackQuery)):
        raise TypeError("Query must be an instance of Message or CallbackQuery")
    return handle_access_denied(query, bot)


def two_factor_auth_required(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator that enforces two-factor authentication for the provided function.

    Args:
        func: The function to be decorated. It must accept `query` and `bot` as arguments.

    Returns:
        Callable[..., Any]: The wrapper function that enforces two-factor authentication.
    """

    def wrapper(query: Union[Message, CallbackQuery], bot: telebot.TeleBot) -> Any:
        # Pre-check for valid query type
        if not isinstance(query, (Message, CallbackQuery)):
            raise TypeError("Query must be an instance of Message or CallbackQuery")

        user = getattr(query, "from_user", None)
        if user is None:
            bot_logger.error("Query does not contain valid user information.")
            return access_denied_handler(query, bot)

        user_id = user.id

        # Determine if the query is a message or a callback query
        handler_type, referer_handler = (
            ("callback_query", query.data)
            if isinstance(query, CallbackQuery)
            else ("message", query.text)
        )

        if user_id in settings.access_control.allowed_admins_ids:
            is_authenticated = session_manager.is_authenticated(user_id)
            bot_logger.debug(
                f"User {user_id} authentication status: {is_authenticated}"
            )

            if not is_authenticated:
                session_manager.set_referer_uri_and_handler_type_for_user(
                    user_id, handler_type, referer_handler
                )
                bot_logger.error(
                    f"User {user_id} not authenticated. Redirecting to authorization page."
                )
                return handle_unauthorized_query(query, bot)

            if session_manager.is_session_expired(user_id):
                session_manager.set_auth_state(user_id, "unauthenticated")
                bot_logger.error(f"Session expired for user {user_id}")
                return handle_unauthorized_query(query, bot)

            bot_logger.debug(f"Access granted to administrative user {user_id}")
            return func(query, bot)
        else:
            bot_logger.error(f"Access denied for user {user_id}. Not an admin.")
            return access_denied_handler(query, bot)

    return wrapper
