#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import sys
from functools import lru_cache
from typing import Tuple, Any, Callable

import loguru
from loguru import logger

from pytmbot.settings import LogsSettings
from pytmbot.utils.utilities import (
    parse_cli_args,
    get_inline_message_full_info,
    get_message_full_info
)


def build_bot_logger() -> loguru.logger:
    """
    Builds a custom logger for the bot.

    This function removes the default logger, creates a new logger, sets the log format and output destination,
    and adds custom log levels for "BLOCKED" and "DENIED".

    Returns:
        loguru.logger: The logger object.
    """
    tabs = "\t" * 2  # Indentation for log messages

    # Remove the default logger
    logger.remove()

    logs_settings = LogsSettings()

    # Cache the log level map
    @lru_cache(maxsize=None)
    def get_log_level_map():
        """
        Returns a set of uppercase log levels from LogsSettings.valid_log_levels.

        Returns:
            set: A set of uppercase log levels.
        """
        return {level.upper() for level in logs_settings.valid_log_levels}

    # Get the log level from command line arguments
    log_level = parse_cli_args().log_level.upper()

    colorize_logs = parse_cli_args().colorize_logs

    # Set the log format and output destination
    logger.add(
        sys.stdout,
        format=logs_settings.bot_logger_format,
        diagnose=True,
        backtrace=True,
        colorize=bool(colorize_logs),
        level=log_level if log_level in get_log_level_map() else 'INFO',  # Set log level to INFO if invalid
        catch=True,
    )

    if log_level == 'DEBUG':
        # Log initialization messages
        messages = [
            "Logger initialized",
            f"{tabs} Log level: {logger.level}",
            f"{tabs} Python executable path: {sys.executable}",
            f"{tabs} Python version: {sys.version}",
            f"{tabs} Python module path: {sys.path}",
            f"{tabs} Python command args: {sys.argv}"
        ]
        logger.debug('\n'.join(messages))

    logger.level("DENIED", no=39, color="<red>")  # Add custom log level for "DENIED"
    logger.level("BLOCKED", no=38, color="<yellow>")  # Add custom log level for "BLOCKED"

    # Return the logger
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
            bot_logger.success(
                f"Finished at @{func.__name__} for user: {username}"
            )
        except Exception as e:
            if bot_logger.level == 10:
                bot_logger.exception(
                    f"Failed at @{func.__name__} - exception: {e}"
                )
            else:
                bot_logger.exception(
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
            bot_logger.success(
                f"Finished at @{func.__name__} for user: {username}"
            )
        except Exception as e:
            if bot_logger.level == 10:
                bot_logger.exception(
                    f"Failed at @{func.__name__} - exception: {e}"
                )
            else:
                bot_logger.exception(
                    f"Failed at @{func.__name__} - exception: {e}"
                )

    return inline_handler_session_wrapper


bot_logger = build_bot_logger()
