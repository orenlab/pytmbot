#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from functools import lru_cache

import telebot
from telebot import AdvancedCustomFilter
from telebot.callback_data import CallbackDataFilter
from telebot.types import CallbackQuery

from app.core import exceptions
from app.core.logs import bot_logger
from app.core.settings.bot_settings import BotSettings
from app.utilities.utilities import parse_cli_args

# Main config
config = BotSettings()

# Set global name
__version__ = 'v0.1.0-dev-20240627'
__author__ = 'Denis Rozhnovskiy <pytelemonbot@mail.ru>'
__license__ = 'MIT'
__repository__ = 'https://github.com/orenlab/pytmbot'
__github_api_url__ = 'https://api.github.com/repos/orenlab/pytmbot/releases/latest'


class ContainersCallbackFilter(AdvancedCustomFilter):
    """
    A custom filter to check if the given CallbackQuery matches the given CallbackDataFilter.
    """
    key = 'containers'

    def check(self, call: CallbackQuery, containers: CallbackDataFilter) -> bool:
        """
        Check if the given CallbackQuery matches the given CallbackDataFilter.

        Args:
            call (CallbackQuery): The CallbackQuery to check.
            containers (CallbackDataFilter): The CallbackDataFilter to match against.

        Returns:
            bool: True if the CallbackQuery matches the CallbackDataFilter, False otherwise.
        """
        # Call the check method of the containers object to determine if the CallbackQuery matches the
        # CallbackDataFilter
        return containers.check(call)


class PyTMBotInstance:
    """
    A class to manage the creation of the pyTMbot instance based on Telebot library

    This class is used to create a singleton instance of the PyTMBot

    Attributes.
    _instance (PyTMBot): The singleton instance of the PyTMBot.

    Methods:
        get_bot_instance()
        __get_bot_token()
    """

    @staticmethod
    @lru_cache(maxsize=1)
    def __get_bot_token():
        """
        Get the bot token based on the bot mode from the command line arguments.

        Returns:
            str: The bot token.
        """
        # Parse command line arguments to get the bot mode
        bot_mode = parse_cli_args()

        # Log the bot mode for debugging purposes
        bot_logger.debug(f"Operational bot mode: {bot_mode.mode}")

        # Return the appropriate bot token based on the bot mode
        return (
            config.dev_bot_token.get_secret_value()  # If bot mode is "dev", return the dev bot token
            if bot_mode.mode == "dev"
            else config.bot_token.get_secret_value()  # Otherwise, return the regular bot token
        )

    @staticmethod
    def get_bot_instance() -> telebot.TeleBot:
        """
        Returns the instance of the TeleBot.

        Returns:
            telebot.TeleBot: The instance of the TeleBot.
        """
        # Check if the instance of the TeleBot is already created
        if PyTMBotInstance._instance is None:
            # Create a new instance of the PyTMBotInstance
            PyTMBotInstance._instance = PyTMBotInstance()

            # Get the bot token
            bot_token = PyTMBotInstance._instance.__get_bot_token()

            # Log the bot token
            bot_logger.debug("Bot token setup successful")

            # Create a new instance of the TeleBot
            PyTMBotInstance._instance.bot = telebot.TeleBot(
                token=bot_token,
                use_class_middlewares=True,
                exception_handler=exceptions.TelebotCustomExceptionHandler(),
            )

            # Add the ContainersCallbackFilter to the TeleBot
            PyTMBotInstance._instance.bot.add_custom_filter(ContainersCallbackFilter())

            # Log that the bot has been configured successfully
            bot_logger.debug("Basic configuration done. We are now continuing with...")

        # Return the instance of the TeleBot
        return PyTMBotInstance._instance.bot


PyTMBotInstance._instance = None
