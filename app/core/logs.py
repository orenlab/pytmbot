#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

import logging
import sys
from functools import partial

from telebot.types import Message, CallbackQuery

from app.utilities.utilities import (
    parse_cli_args,
    find_in_args,
    find_in_kwargs
)


def build_bot_logger() -> logging.Logger:
    """
    Builds a custom logger for the bot.

    Returns:
        logging.Logger: The logger object.
    """
    # Get the log level from command line arguments
    log_level = parse_cli_args().log_level

    # Create a logger with the name 'pyTMbot'
    logger = logging.getLogger('pyTMbot')
    logger.setLevel(log_level.upper())

    # Set the date format for the log messages
    date_format = '%Y-%m-%d %H:%M:%S'

    # Create a stream handler to output logs to stdout
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s' +
        (' [%(filename)s | %(funcName)s:%(lineno)d]' if log_level == 'DEBUG' else ''), datefmt=date_format
    ))

    # Add the handler to the logger
    logger.addHandler(handler)

    # Disable propagation of logs to parent loggers
    logger.propagate = False

    # Override the error method to include exception information
    if log_level == 'DEBUG':
        logger.error = partial(logger.error, exc_info=True)

    return logger


# Logger on common instance
bot_logger = build_bot_logger()


def get_message_full_info(*args, **kwargs):
    """
    Get full info for inline handlers logs.

    Args:
        *args (): Any
        **kwargs (): Any

    Returns:
        Tuple[Union[str, None], Union[int, None], Union[str, None], Union[bool, None], Union[str, None]]:
            Objects to write to the logs. Returns a tuple containing the username, user ID, language code,
            is_bot flag, and text of the message. If the message is not found in args or kwargs, returns
            "None" for all values.
    """

    # Find message in args
    message_args = find_in_args(args, Message)
    if message_args is not None:
        return (
            message_args.from_user.username,  # Username of the message sender
            message_args.from_user.id,  # User ID of the message sender
            message_args.from_user.language_code,  # Language code of the message sender
            message_args.from_user.is_bot,  # Flag indicating if the message sender is a bot
            message_args.text  # Text of the message
        )

    # Find message in kwargs
    message_kwargs = find_in_kwargs(kwargs, Message)
    if message_kwargs is not None:
        return (
            message_kwargs.from_user.username,  # Username of the message sender
            message_kwargs.from_user.id,  # User ID of the message sender
            message_kwargs.from_user.language_code,  # Language code of the message sender
            message_kwargs.from_user.is_bot,  # Flag indicating if the message sender is a bot
            message_kwargs.text  # Text of the message
        )

    # Return "None" for all values if message is not found
    return "None", "None", "None", "None", "None"


def get_inline_message_full_info(*args, **kwargs):
    """
    Get full info for inline handlers logs.

    Args:
        *args (Any): Variable length argument list.
        **kwargs (Any): Arbitrary keyword arguments.

    Returns:
        Tuple[Union[str, None], Union[int, None], Union[bool, None]]:
            A tuple containing the username, user ID, and is_bot flag of the message sender.
            If the message is not found in args or kwargs, returns "None" for all values.
    """
    # Find message in args
    message_args = find_in_args(args, CallbackQuery)
    if message_args is not None:
        return (
            message_args.message.from_user.username,  # Username of the message sender
            message_args.message.from_user.id,  # User ID of the message sender
            message_args.message.from_user.is_bot  # Flag indicating if the message sender is a bot
        )

    # Find message in kwargs
    message_kwargs = find_in_kwargs(kwargs, CallbackQuery)
    if message_kwargs is not None:
        return (
            message_kwargs.message.from_user.username,  # Username of the message sender
            message_kwargs.message.from_user.id,  # User ID of the message sender
            message_kwargs.message.from_user.is_bot  # Flag indicating if the message sender is a bot
        )

    # Return "None" for all values if message is not found
    return "None", "None", "None"


def logged_handler_session(func):
    """
    Decorator function that logs the handling session of a handler function.

    Args:
        func (function): The handler function to be logged.

    Returns:
        function: The wrapped handler function.
    """

    def handler_session_wrapper(*args, **kwargs):
        """
        Wrapper function that records logs of work with handlers.

        Args:
            *args (tuple): Positional arguments passed to the handler function.
            **kwargs (dict): Keyword arguments passed to the handler function.

        Returns:
            object: The result of the handler function.
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
                    f"Failed @{func.__name__} - exception: {e}"
                )
            else:
                bot_logger.error(
                    f"Failed @{func.__name__} - exception: {e}"
                )

    return handler_session_wrapper


def logged_inline_handler_session(func):
    """
    Logging inline handlers

    Args:
        func (): Any handler

    Returns:
        object: Logs
    """

    def inline_handler_session_wrapper(*args, **kwargs):
        """
        Recording logs of work with handlers

        Args:
            *args (): tuple[Any | none]
            **kwargs (): dict[str, Any]

        Returns:
            object: Any
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
                    f"Failed @{func.__name__} - exception: {e}"
                )
            else:
                bot_logger.error(
                    f"Failed @{func.__name__} - exception: {e}"
                )

    return inline_handler_session_wrapper
