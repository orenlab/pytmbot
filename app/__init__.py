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

from app.core import exceptions
from app.core.settings.bot_settings import BotSettings

# Main config
config = BotSettings()

# Set global name
__version__ = '0.0.8-dev-20240524'
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
            bot_logger.error(exception, exc_info=False)
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


# Bot one common instance
bot = build_bot_instance()

# Logger on common instance
bot_logger = build_bot_logger()
