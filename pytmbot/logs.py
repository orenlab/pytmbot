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
    get_message_full_info,
)


def build_bot_logger() -> loguru.logger:
    """
    Builds a custom logger for the bot.

    This function removes the default logger, creates a new logger, sets the log format and output destination,
    and adds custom log levels for "BLOCKED" and "DENIED".

    Returns:
        loguru.Logger: The logger object.
    """
    tabs = "\t" * 2  # Indentation for log messages

    # Remove the default logger
    logger.remove()

    logs_settings = LogsSettings()

    # Cache the log level map
    @lru_cache(maxsize=None)
    def get_log_level_map() -> set:
        """
        Returns a set of uppercase log levels from LogsSettings.valid_log_levels.

        Returns:
            set: A set of uppercase log levels.
        """
        return {level.upper() for level in logs_settings.valid_log_levels}

    # Get the log level and colorize option from command line arguments
    cli_args = parse_cli_args()
    log_level = cli_args.log_level.upper()
    colorize_logs = cli_args.colorize_logs

    # Set the log format and output destination
    logger.add(
        sys.stdout,
        format=logs_settings.bot_logger_format,
        diagnose=True,
        backtrace=True,
        colorize=bool(colorize_logs),
        level=(
            log_level if log_level in get_log_level_map() else "INFO"
        ),  # Set log level to INFO if invalid
        catch=True,
    )

    if log_level == "DEBUG":
        # Log initialization messages
        logger.debug(
            "\n".join(
                [
                    "Logger initialized",
                    f"{tabs} Log level: {logger.level}",
                    f"{tabs} Python executable path: {sys.executable}",
                    f"{tabs} Python version: {sys.version}",
                    f"{tabs} Python module path: {sys.path}",
                    f"{tabs} Python command args: {sys.argv}",
                ]
            )
        )

    logger.level("DENIED", no=39, color="<red>")  # Add custom log level for "DENIED"
    logger.level(
        "BLOCKED", no=38, color="<yellow>"
    )  # Add custom log level for "BLOCKED"

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
        """
        # Get information about the message
        username, user_id, language_code, is_bot, text = get_message_full_info(
            *args, **kwargs
        )

        # Log the start of the handling session
        logger.info(
            f"Start handling session @{func.__name__}: "
            f"User: {username} - UserID: {user_id} - language: {language_code} - "
            f"is_bot: {is_bot}"
        )
        logger.debug(
            f"Debug handling session @{func.__name__}: "
            f"Text: {text} - arg: {str(args)} - kwarg: {str(kwargs)}"
        )
        try:
            result = func(*args, **kwargs)
            logger.success(f"Finished at @{func.__name__} for user: {username}")
            return result
        except Exception as e:
            logger.exception(f"Failed at @{func.__name__} - exception: {e}")
            raise

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
        """
        username, user_id, is_bot = get_inline_message_full_info(*args, **kwargs)

        logger.info(
            f"Start handling session @{func.__name__}: "
            f"User: {username} - UserID: {user_id} - is_bot: {is_bot}"
        )
        logger.debug(
            f"Debug inline handling session @{func.__name__}: "
            f"- arg: {str(args)} - kwarg: {str(kwargs)}"
        )
        try:
            result = func(*args, **kwargs)
            logger.success(f"Finished at @{func.__name__} for user: {username}")
            return result
        except Exception as e:
            logger.exception(f"Failed at @{func.__name__} - exception: {e}")
            raise

    return inline_handler_session_wrapper


# Initialize the logger
bot_logger = build_bot_logger()
