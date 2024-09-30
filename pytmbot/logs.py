import sys
from functools import lru_cache
from typing import Tuple, Any, Callable

import loguru
from loguru import logger

from pytmbot.settings import LogsSettings
from pytmbot.utils.utilities import (
    parse_cli_args,
    get_inline_message_full_info,
    get_message_full_info, is_running_in_docker,
)


def build_bot_logger() -> loguru.logger:
    """
    Builds a custom logger for the bot with custom levels and configurations.

    This function removes the default logger, sets a new logger with specific log levels, formats, and output.

    Returns:
        loguru.Logger: Configured logger object.
    """
    tabs = "\t" * 2  # Indentation for log messages
    logger.remove()  # Remove default logger
    logs_settings = LogsSettings()

    @lru_cache(maxsize=None)
    def get_log_level_map() -> set:
        """Returns a set of valid uppercase log levels."""
        return {level.upper() for level in logs_settings.valid_log_levels}

    cli_args = parse_cli_args()
    log_level = cli_args.log_level.upper()
    colorize_logs = cli_args.colorize_logs

    # Add the logger output configuration
    logger.add(
        sys.stdout,
        format=logs_settings.bot_logger_format,
        diagnose=True,
        backtrace=True,
        colorize=bool(colorize_logs),
        level=log_level if log_level in get_log_level_map() else "INFO",
        catch=True,
    )

    # Log startup information if in DEBUG mode
    if log_level == "DEBUG":
        logger.debug(
            f"Logger initialized\n"
            f"{tabs}Log level: {logger.level}\n"
            f"{tabs}Python path: {sys.executable}\n"
            f"{tabs}Python version: {sys.version}\n"
            f"{tabs}Module path: {sys.path}\n"
            f"{tabs}Command args: {sys.argv}\n"
            f"{tabs}Running on: {"Docker" if is_running_in_docker() else "Host"}"
        )

    # Custom log levels
    logger.level("DENIED", no=39, color="<red>")
    logger.level("BLOCKED", no=38, color="<yellow>")

    return logger


def logged_handler_session(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator that logs the handling session of a handler function.

    Args:
        func (Callable[..., Any]): Handler function to wrap and log.

    Returns:
        Callable[..., Any]: The wrapped handler function.
    """

    def handler_session_wrapper(*args: Tuple[Any, ...], **kwargs: dict) -> Any:
        # Extract message info for logging
        username, user_id, language_code, is_bot, text = get_message_full_info(
            *args, **kwargs
        )

        logger.info(
            f"Start handling @{func.__name__} session: User: {username}, UserID: {user_id}, "
            f"Language: {language_code}, Is bot: {is_bot}"
        )
        logger.debug(f"Arguments: {args}, Keyword arguments: {kwargs}, Text: {text}")

        try:
            result = func(*args, **kwargs)
            logger.success(f"Finished @{func.__name__} session for user: {username}")
            return result
        except Exception as e:
            logger.exception(
                f"Error in @{func.__name__} session for user: {username}, exception: {e}"
            )
            raise

    return handler_session_wrapper


def logged_inline_handler_session(func: Callable[..., Any]) -> Callable[..., Any]:
    """
    Decorator that logs the handling session of an inline handler function.

    Args:
        func (Callable[..., Any]): Inline handler function to wrap and log.

    Returns:
        Callable[..., Any]: The wrapped inline handler function.
    """

    def inline_handler_session_wrapper(*args: Tuple[Any, ...], **kwargs: dict) -> Any:
        username, user_id, is_bot = get_inline_message_full_info(*args, **kwargs)

        logger.info(
            f"Start inline session @{func.__name__}: User: {username}, UserID: {user_id}, Is bot: {is_bot}"
        )
        logger.debug(f"Arguments: {args}, Keyword arguments: {kwargs}")

        try:
            result = func(*args, **kwargs)
            logger.success(
                f"Finished inline session @{func.__name__} for user: {username}"
            )
            return result
        except Exception as e:
            logger.exception(
                f"Error in inline session @{func.__name__} for user: {username}, exception: {e}"
            )
            raise

    return inline_handler_session_wrapper


# Initialize the logger
bot_logger = build_bot_logger()
