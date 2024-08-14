from typing import Union, Callable, Any

from telebot.types import Message, CallbackQuery

from app import PyTMBotInstance, config, session_manager, bot_logger
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
            is_user_authenticated = session_manager.is_authenticated(user_id)
            bot_logger.debug(f"User {user_id} is authenticated: {is_user_authenticated}")
            if not is_user_authenticated:
                # Create a new authorized user
                return handle_unauthorized_query(query)
            elif session_manager.is_session_expired(user_id):
                session_manager.set_auth_state(user_id, 'unauthenticated')
                bot_logger.error(f"Session expired for user {user_id}")
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
