#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

import argparse
import logging
import sys

import telebot
from telebot import ExceptionHandler
from telebot.types import Message, CallbackQuery

from app.core import exceptions
from app.core.settings.bot_settings import BotSettings

# Main config
config = BotSettings()

# Set global name
__version__ = '0.0.8-dev-20240529'
__author__ = 'Denis Rozhnovskiy <pytelemonbot@mail.ru>'
__license__ = 'MIT'
__repository__ = 'https://github.com/orenlab/pytmbot'
__github_api_url__ = 'https://api.github.com/repos/orenlab/pytmbot/releases/latest'


class CustomExceptionHandler(ExceptionHandler):
    """Custom exception handler that handles exceptions raised during the execution"""

    def handle(self, exception):
        if bot_logger.level == 20:
            if "Bad getaway" in str(exception):
                bot_logger.error('Connection error to Telegram API. Bad getaway. Error code: 502')
            else:
                bot_logger.error(f"Error occurred: {exception}", exc_info=False)
        else:
            bot_logger.error(f"Error occurred: {exception}", exc_info=True)
        return True


def parse_cli_args() -> argparse.Namespace:
    """Parse command line args (see Dockerfile)"""
    parser = argparse.ArgumentParser(description="PyTMBot CLI")
    parser.add_argument(
        "--mode",
        choices=["dev", "prod"],
        type=str,
        help="PyTMBot mode (dev or prod)",
        default="prod")
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "ERROR"],
        type=str,
        help="Log level",
        default="CRITICAL")
    return parser.parse_args()


def build_bot_instance() -> telebot.TeleBot:
    """Build PyTMBot instance"""
    bot_mode = parse_cli_args()

    match bot_mode.mode:
        case "dev":
            configured_bot = telebot.TeleBot(
                config.dev_bot_token.get_secret_value(),
                use_class_middlewares=True,
                exception_handler=CustomExceptionHandler()
            )
        case "prod":
            configured_bot = telebot.TeleBot(
                config.bot_token.get_secret_value(),
                use_class_middlewares=True,
                exception_handler=CustomExceptionHandler()
            )
        case _:
            raise ValueError(f"Invalid PyTMBot mode: {bot_mode.mode}, use -h option to see more")

    return configured_bot


def build_bot_logger() -> logging.Logger:
    """Build bot custom logger"""
    logs_level = parse_cli_args()
    logger = logging.getLogger('pyTMbot')
    handler = logging.StreamHandler(sys.stdout)
    str_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s [%(filename)s | %(funcName)s:%(lineno)d]"
    date_format = '%Y-%m-%d %H:%M:%S'
    formatter = logging.Formatter(fmt=str_format, datefmt=date_format)
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.propagate = False
    match logs_level.log_level:
        case "DEBUG":
            logger.setLevel(logging.DEBUG)
        case "INFO":
            logger.setLevel(logging.INFO)
        case "ERROR":
            logger.setLevel(logging.ERROR)
        case "CRITICAL":
            logger.setLevel(logging.CRITICAL)
        case _:
            raise ValueError(f"Unknown log level: {logs_level}, use -h option to see more")

    return logger


def find_in_args(args, target_type):
    """Find args in args dictionary"""
    for arg in args:
        if isinstance(arg, target_type):
            return arg


def find_in_kwargs(kwargs, target_type):
    """Find kwargs in kwargs dictionary"""
    return find_in_args(kwargs.values(), target_type)


def get_message_full_info(*args, **kwargs):
    """Get full info for logs"""
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


def get_inline_message_full_info(*args, **kwargs):
    """Get full info for logs"""
    message_args = find_in_args(args, CallbackQuery)
    if message_args is not None:
        return (message_args.message.from_user.username,
                message_args.message.from_user.id,
                message_args.message.from_user.is_bot,
                message_args.message.text
                )

    message_kwargs = find_in_kwargs(kwargs, CallbackQuery)
    if message_kwargs is not None:
        return (message_kwargs.message.from_user.username,
                message_kwargs.message.from_user.id,
                message_kwargs.message.from_user.is_bot,
                message_kwargs.message.text
                )

    return "None", "None", "None", "None"


def logged_handler_session(func):
    """Logging default handlers"""

    def handler_session_wrapper(*args, **kwargs):
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
            bot_logger.error(
                f"Failed @{func.__name__} - exception {e}", exc_info=False
            )

    return handler_session_wrapper


def logged_inline_handler_session(func):
    """Logging inline handlers"""

    def inline_handler_session_wrapper(*args, **kwargs):
        username, user_id, is_bot, text = get_inline_message_full_info(*args, **kwargs)

        bot_logger.info(
            f"Start handling session @{func.__name__}: "
            f"User: {username} - UserID: {user_id} - is_bot: {is_bot}"
        )
        bot_logger.debug(
            f"Debug inline handling session @{func.__name__}: "
            f"Text: {text} - arg: {str(args)} - kwarg: {str(kwargs)}"
        )
        try:
            func(*args, **kwargs)
            bot_logger.info(
                f"Finished at @{func.__name__} for user: {username}"
            )
        except Exception as e:
            bot_logger.error(
                f"Failed @{func.__name__} - exception {e}", exc_info=False
            )

    return inline_handler_session_wrapper


# Bot one common instance
bot = build_bot_instance()

# Logger on common instance
bot_logger = build_bot_logger()
