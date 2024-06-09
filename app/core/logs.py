#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

import logging
import sys
from functools import partial
from typing import List, Callable, Any, Tuple

from telebot.types import Message, CallbackQuery

from app.utilities.utilities import (
    parse_cli_args,
    find_in_args,
    find_in_kwargs
)


class BotLogger:
    """
    Custom logger for the bot. Uses the 'pyTMbot' logger name.

    Attributes:
        _logger (logging.Logger): The logger object.

    Methods:
        get_logger()

    Returns:
        logging.Logger: The logger object.
    """
    _logger = None

    @classmethod
    def get_logger(cls) -> logging.Logger:
        """
        Retrieves the logger object for the bot. If the logger object is not set, it initializes it with the 'pyTMbot' logger name.

        Returns:
            logging.Logger: The logger object.
        """
        cls._logger = cls._logger or logging.getLogger('pyTMbot')
        return cls._logger


def build_bot_logger() -> logging.Logger:
    """
    Builds a custom logger for the bot.

    Returns:
        logging.Logger: The logger object.

    This function creates a logger object for the bot and configures it based on the log level
    provided in the command line arguments. The logger object is configured to output logs to
    the standard output (stdout) and has a date format of '%Y-%m-%d %H:%M:%S'. If the log level
    is set to 'DEBUG', the log format includes the file name and line number. The logger object
    is configured to disable propagation of logs to parent loggers and override the error method
    to include exception information if the log level is 'DEBUG'.
    """

    # Get the log level from command line arguments
    known_log_levels: List[str] = ['ERROR', 'INFO', 'DEBUG']
    log_level = parse_cli_args().log_level

    # Create a logger object for the bot
    logger = BotLogger.get_logger()

    # Set the log level based on the command line argument
    logger.setLevel(log_level.upper() if log_level in known_log_levels else 'INFO')

    # Set the date format for the log messages
    date_format = '%Y-%m-%d %H:%M:%S'

    # Create a stream handler to output logs to stdout
    handler = logging.StreamHandler(sys.stdout)
    log_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    # Add file name and line number to log format if log level is DEBUG
    if log_level == 'DEBUG':
        log_format += ' [%(filename)s | %(funcName)s:%(lineno)d]'

    # Set the log format for the handler
    handler.setFormatter(logging.Formatter(log_format, datefmt=date_format))

    # Add the handler to the logger
    logger.addHandler(handler)

    # Disable propagation of logs to parent loggers
    logger.propagate = False

    # Override the error method to include exception information if log level is DEBUG
    if log_level == 'DEBUG':
        logger.error = partial(logger.error, exc_info=True)

    logger.debug("Logger initialized")
    logger.debug(f"Logger level: {logger.level}")

    return logger


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
                    f"Failed @{func.__name__} - exception: {e}"
                )
            else:
                bot_logger.error(
                    f"Failed @{func.__name__} - exception: {e}"
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
                    f"Failed @{func.__name__} - exception: {e}"
                )
            else:
                bot_logger.error(
                    f"Failed @{func.__name__} - exception: {e}"
                )

    return inline_handler_session_wrapper


# Logger on common instance
bot_logger = build_bot_logger()
