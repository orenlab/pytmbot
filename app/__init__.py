#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

import telebot

from app.core import exceptions
from app.core.settings.bot_settings import BotSettings
from app.utilities.utilities import parse_cli_args

# Main config
config = BotSettings()

# Set global name
__version__ = 'v0.0.9-dev-20240605'
__author__ = 'Denis Rozhnovskiy <pytelemonbot@mail.ru>'
__license__ = 'MIT'
__repository__ = 'https://github.com/orenlab/pytmbot'
__github_api_url__ = 'https://api.github.com/repos/orenlab/pytmbot/releases/latest'


def build_bot_instance() -> telebot.TeleBot:
    """
    Build PyTMBot instance based on the provided mode.

    Returns:
        telebot.TeleBot: The configured PyTMBot instance.

    Raises:
        ValueError: If the provided mode is invalid.
    """
    bot_mode = parse_cli_args()

    bot_token = config.dev_bot_token.get_secret_value() if bot_mode.mode == "dev" else config.bot_token.get_secret_value()

    return telebot.TeleBot(
        bot_token,
        use_class_middlewares=True,
        exception_handler=exceptions.TelebotCustomExceptionHandler()
    )


# Bot one common instance
bot = build_bot_instance()
