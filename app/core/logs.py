#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
import logging
import sys

from telebot.types import Message, CallbackQuery

from app.utilities.utilities import (
    parse_cli_args,
    find_in_args,
    find_in_kwargs
)


def build_bot_logger() -> logging.Logger:
    """
    Build bot custom logger

    Args:
        -

    Returns:
        object: logger

    """
    logs_level = parse_cli_args()

    logger = logging.getLogger('pyTMbot')
    handler = logging.StreamHandler(sys.stdout)

    if logs_level.log_level == "DEBUG":
        str_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s [%(filename)s | %(funcName)s:%(lineno)d]"
    else:
        str_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

    date_format = '%Y-%m-%d %H:%M:%S'
    formatter = logging.Formatter(fmt=str_format, datefmt=date_format)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False

    if logs_level.log_level == "DEBUG":
        logger.setLevel(logging.DEBUG)
    elif logs_level.log_level == "INFO":
        logger.setLevel(logging.INFO)
    elif logs_level.log_level == "WARN":
        logger.setLevel(logging.WARN)
    elif logs_level.log_level == "ERROR":
        logger.setLevel(logging.ERROR)
    elif logs_level.log_level == "CRITICAL":
        logger.setLevel(logging.CRITICAL)
    else:
        raise ValueError(f"Unknown log level: {logs_level}, use -h option to see more")

    return logger


def get_message_full_info(*args, **kwargs):
    """
    Get full info for inline handlers logs

    Args:
        *args (): Any
        **kwargs (): Any

    Returns:
        object: Objects to write to the logs
    """

    message_args = find_in_args(args, Message)
    if message_args is not None:
        return (message_args.from_user.username,
                message_args.from_user.id,
                message_args.from_user.language_code,
                message_args.from_user.is_bot,
                message_args.text
                )

    message_kwargs = find_in_kwargs(kwargs, Message)
    if message_kwargs is not None:
        return (message_kwargs.from_user.username,
                message_kwargs.from_user.id,
                message_kwargs.from_user.language_code,
                message_kwargs.from_user.is_bot,
                message_kwargs.text
                )

    return "None", "None", "None", "None", "None"


def get_inline_message_full_info(*args, **kwargs) -> object:
    """
    Get full info for inline handlers logs

    Args:
        *args (): Any
        **kwargs (): Any

    Returns:
        object: Objects to write to the logs
    """
    message_args = find_in_args(args, CallbackQuery)
    if message_args is not None:
        return (message_args.message.from_user.username,
                message_args.message.from_user.id,
                message_args.message.from_user.is_bot
                )

    message_kwargs = find_in_kwargs(kwargs, CallbackQuery)
    if message_kwargs is not None:
        return (message_kwargs.message.from_user.username,
                message_kwargs.message.from_user.id,
                message_kwargs.message.from_user.is_bot,
                )

    return "None", "None", "None"


def logged_handler_session(func):
    """
    Logging handlers

    Args:
        func (): Any handler

    Returns:
        object: Logs
    """

    def handler_session_wrapper(*args, **kwargs):
        """
        Recording logs of work with handlers

        Args:
            *args (): tuple[Any | none]
            **kwargs (): dict[str, Any]

        Returns:
            object: Any
        """
        username, user_id, language_code, is_bot, text = get_message_full_info(*args, **kwargs)

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
                    f"Failed @{func.__name__} - exception: {e}", exc_info=False
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
                    f"Failed @{func.__name__} - exception: {e}", exc_info=False
                )

    return inline_handler_session_wrapper


# Logger on common instance
bot_logger = build_bot_logger()
