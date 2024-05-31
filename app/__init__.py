#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

import telebot

from app.core import exceptions
from app.core.logs import bot_logger
from app.core.settings.bot_settings import BotSettings
from app.utilities.utilities import parse_cli_args

# Main config
config = BotSettings()

# Set global name
__version__ = 'v0.0.9-dev-20240531'
__author__ = 'Denis Rozhnovskiy <pytelemonbot@mail.ru>'
__license__ = 'MIT'
__repository__ = 'https://github.com/orenlab/pytmbot'
__github_api_url__ = 'https://api.github.com/repos/orenlab/pytmbot/releases/latest'


def build_bot_instance() -> telebot.TeleBot:
    """Build PyTMBot instance"""
    bot_mode = parse_cli_args()

    match bot_mode.mode:
        case "dev":
            configured_bot = telebot.TeleBot(
                config.dev_bot_token.get_secret_value(),
                use_class_middlewares=True,
                exception_handler=exceptions.TelebotCustomExceptionHandler()
            )
        case "prod":
            configured_bot = telebot.TeleBot(
                config.bot_token.get_secret_value(),
                use_class_middlewares=True,
                exception_handler=exceptions.TelebotCustomExceptionHandler()
            )
        case _:
            raise ValueError(f"Invalid PyTMBot mode: {bot_mode.mode}, use -h option to see more")

    return configured_bot


# Bot one common instance
bot = build_bot_instance()
