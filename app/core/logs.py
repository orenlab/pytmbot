#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

import sys
from typing import Callable, Any, Tuple

import loguru
from loguru import logger

from app.utilities.utilities import (
    parse_cli_args,
    get_message_full_info,
    get_inline_message_full_info
)


def build_bot_logger() -> loguru.logger:
    """
    Builds a custom logger for the bot.

    Returns:
        loguru.logger: The logger object.
    """
    # Get the log level from command line arguments
    valid_log_levels = ['ERROR', 'INFO', 'DEBUG']
    log_level = parse_cli_args().log_level.lower()

    # Set the log level
    logger.level(log_level if log_level in valid_log_levels else 'INFO')

    # Log initialization messages
    logger.debug("Logger initialized")
    logger.debug(f"Log level: {logger.level}")
    logger.debug(f"Python executable path: {sys.executable}")
    logger.debug(f"Python version: {sys.version}")
    logger.debug(f"Python module path: {sys.path}")
    logger.debug(f"Python command args: {sys.argv}")

    return logger


def logged_handler_session(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator function that logs the handling session of a handler function.

    Args:
        func (Callable[..., Any]): The handler function to be logged.

    Returns:
        Callable[..., Any]: The wrapped handler function.
    """

    def handler_session_wrapper(*args: Tuple[Any, ...], **kwargs: dict) -> Any:
        """
        Wrapper function that records logs of work with handlers.

        Args:
            *args (Tuple[Any, ...]): Positional arguments passed to the handler function.
            **kwargs (dict): Keyword arguments passed to the handler function.

        Returns:
            Any: The result of the handler function.
            message: Message = args[0]
            username = message.from_user.username
            user_id = message.from_user.id
            language_code = message.from_user.language_code
            is_bot = message.from_user.is_bot
            text = message.text
        """
        # Get information about the message
        username, user_id, language_code, is_bot, text = get_message_full_info(*args, **kwargs)

        # Log the start of the handling session
        bot_logger.info(
            f"Start handling session @{func.__name__}: "
            f"User: {username} - UserID: {user_id} - language: {language_code} - "
            f"is_bot: {is_bot}"
        )
        bot_logger.debug(
            f"Debug handling session @{func.__name__}: "
            f"Text: {text} - arg: {str(args)} - kwarg: {str(kwargs)}"
        )
        try:
            func(*args, **kwargs)
            bot_logger.info(
                f"Finished at @{func.__name__} for user: {username}"
            )
        except Exception as e:
            if bot_logger.level == 10:
                bot_logger.exception(
                    f"Failed at @{func.__name__} - exception: {e}"
                )
            else:
                bot_logger.error(
                    f"Failed at @{func.__name__} - exception: {e}"
                )

    return handler_session_wrapper


def logged_inline_handler_session(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator function that logs the handling session of an inline handler function.

    Args:
        func (Callable[..., Any]): The inline handler function to be logged.

    Returns:
        Callable[..., Any]: The wrapped inline handler function.
    """

    def inline_handler_session_wrapper(*args: Tuple[Any, ...], **kwargs: dict) -> Any:
        """
        Wrapper function that records logs of work with inline handlers.

        Args:
            *args (Tuple[Any, ...]): Positional arguments passed to the inline handler function.
            **kwargs (dict): Keyword arguments passed to the inline handler function.

        Returns:
            Any: The result of the inline handler function.
            message: Message = args[0]
            username (str): The username of the user who sent the message.
            user_id (int): The ID of the user who sent the message.
            is_bot (bool): Whether the user is a bot or not.
        """
        username, user_id, is_bot = get_inline_message_full_info(*args, **kwargs)

        bot_logger.info(
            f"Start handling session @{func.__name__}: "
            f"User: {username} - UserID: {user_id} - is_bot: {is_bot}"
        )
        bot_logger.debug(
            f"Debug inline handling session @{func.__name__}: "
            f"- arg: {str(args)} - kwarg: {str(kwargs)}"
        )
        try:
            func(*args, **kwargs)
            bot_logger.info(
                f"Finished at @{func.__name__} for user: {username}"
            )
        except Exception as e:
            if bot_logger.level == 10:
                bot_logger.exception(
                    f"Failed at @{func.__name__} - exception: {e}"
                )
            else:
                bot_logger.error(
                    f"Failed at @{func.__name__} - exception: {e}"
                )

    return inline_handler_session_wrapper


# Logger on common instance
bot_logger = build_bot_logger()
