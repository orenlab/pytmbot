import sys
from functools import lru_cache, wraps
from typing import Tuple, Any, Callable, Set

import loguru
from loguru import logger

from pytmbot.settings import LogsSettings
from pytmbot.utils.utilities import (
    parse_cli_args,
    get_inline_message_full_info,
    get_message_full_info,
    is_running_in_docker,
    sanitize_exception,
)


@lru_cache(maxsize=1)
def get_log_level_map(valid_log_levels: tuple) -> Set[str]:
    """Returns a set of valid uppercase log levels."""
    return {level.upper() for level in valid_log_levels}


def build_bot_logger() -> loguru.logger:
    """
    Builds a custom logger for the bot with custom levels and configurations.

    Returns:
        loguru.Logger: Configured logger object.
    """
    logger.remove()
    logs_settings = LogsSettings()
    cli_args = parse_cli_args()

    log_level = cli_args.log_level.upper()
    if log_level not in get_log_level_map(tuple(logs_settings.valid_log_levels)):
        log_level = "INFO"

    logger.add(
        sys.stdout,
        format=logs_settings.bot_logger_format,
        diagnose=True,
        backtrace=True,
        colorize=bool(cli_args.colorize_logs),
        level=log_level,
        catch=True,
    )

    if log_level == "DEBUG":
        logger.debug(
            "Logger initialized\n"
            f"  Log level: {logger.level}\n"
            f"  Python path: {sys.executable}\n"
            f"  Python version: {sys.version}\n"
            f"  Module path: {sys.path}\n"
            f"  Command args: {sys.argv}\n"
            f"  Running on: {'Docker' if is_running_in_docker() else 'Host'}"
        )

    # Custom log levels
    logger.level("DENIED", no=39, color="<red>")
    logger.level("BLOCKED", no=38, color="<yellow>")

    return logger


def create_session_logger(is_inline: bool = False):
    """Factory function for creating session loggers."""

    def session_decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        def wrapper(*args: Tuple[Any, ...], **kwargs: dict) -> Any:
            get_info = get_inline_message_full_info if is_inline else get_message_full_info
            session_type = "inline session" if is_inline else "handling"

            info = get_info(*args, **kwargs)
            username, user_id = info[0], info[1]

            logger.info(
                f"Start {session_type} @{func.__name__}: "
                f"User: {username}, UserID: {user_id}"
            )
            logger.debug(f"Arguments: {args}, Keyword arguments: {kwargs}")

            try:
                result = func(*args, **kwargs)
                logger.success(
                    f"Finished {session_type} @{func.__name__} for user: {username}"
                )
                return result
            except Exception as e:
                logger.exception(
                    f"Error in {session_type} @{func.__name__} "
                    f"for user: {username}, exception: {sanitize_exception(e)}"
                )
                raise

        return wrapper

    return session_decorator


# Create specific decorators using the factory
logged_handler_session = create_session_logger(is_inline=False)
logged_inline_handler_session = create_session_logger(is_inline=True)

# Initialize the logger
bot_logger = build_bot_logger()
