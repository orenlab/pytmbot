#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

import logging
import telebot
import argparse

from app.core.settings.bot_settings import token_settings, BotSettings
from app.core import exceptions

# Main config
config = BotSettings()

# Set global name
__version__ = '0.0.1'
__author__ = 'Denis Rozhnovskiy <pytelemonbot@mail.ru>'
__license__ = 'MIT'
__repository__ = 'https://github.com/orenlab/pytmbot'


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


def build_logger(name: str) -> logging.Logger:
    """Build logger with specified module name and log level"""
    logs_level = parse_cli_args()

    match logs_level.log_level:
        case "DEBUG":
            telebot.logger.setLevel(logging.DEBUG)
        case "INFO":
            telebot.logger.setLevel(logging.INFO)
        case "ERROR":
            telebot.logger.setLevel(logging.ERROR)
        case "CRITICAL":
            telebot.logger.setLevel(logging.CRITICAL)
        case _:
            raise ValueError(f"Unknown log level: {logs_level}, use -h option to see more")

    return telebot.logger


def init_bot() -> telebot.TeleBot:
    """Build PyTMBot instance"""
    bot_mode = parse_cli_args()

    match bot_mode.mode:
        case "dev":
            configured_bot = telebot.TeleBot(
                token_settings.dev_bot_token.get_secret_value(),
                use_class_middlewares=True
            )
        case "prod":
            configured_bot = telebot.TeleBot(
                token_settings.bot_token.get_secret_value(),
                use_class_middlewares=True
            )
        case _:
            raise ValueError(f"Invalid PyTMBot mode: {bot_mode.mode}, use -h option to see more")

    return configured_bot


# Bot one common instance
bot = init_bot()
