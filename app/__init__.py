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


class PytmbotInstance:
    """
    A class to manage the PyTMBot instance. This class provides a method to build a PyTMBot instance based on the
    provided mode.

    Attributes:
        bot (telebot.TeleBot): The PyTMBot instance.

    Raises:
        ValueError: If the provided mode is invalid.
    """

    def __init__(self):
        """
        Initializes the object by setting the `bot` attribute to None.

        This attribute is used to store an instance of the bot object.
        """
        self.bot = None

    @lru_cache(maxsize=1)
    def __get_bot_token(self) -> str:
        """
        Get the bot token based on the bot mode.

        This method retrieves the bot token from the configuration based on the bot mode.
        The bot mode is determined from the command line arguments.

        Returns:
            str: The bot token.
        """
        # Get the bot mode from the command line arguments
        bot_mode = parse_cli_args()

        # Log the bot mode
        bot_logger.debug(f"Operational bot mode: {bot_mode.mode}")

        # Return the appropriate bot token based on the bot mode
        return (
            config.dev_bot_token.get_secret_value()
            if bot_mode.mode == "dev"
            else config.bot_token.get_secret_value()
        )

    @lru_cache(maxsize=1)
    def build_bot_instance(self) -> telebot.TeleBot:
        """
        Constructs a PyTMBot instance with the provided mode.

        Returns:
            telebot.TeleBot: The configured PyTMBot instance.

        Raises:
            ValueError: If the mode provided is invalid.
        """
        # Check if bot instance already exists
        if self.bot is None:
            # Get the bot token based on the bot mode
            bot_token = self.__get_bot_token()

            # Log the bot token
            bot_logger.debug("Bot token setup successful")

            # Create a new TeleBot instance with the bot token and custom middleware
            self.bot = telebot.TeleBot(
                token=bot_token,
                use_class_middlewares=True,
                exception_handler=exceptions.TelebotCustomExceptionHandler(),
            )

            # Add a custom filter for callback queries to the bot
            self.bot.add_custom_filter(ContainersCallbackFilter())

            # Log that the bot has been configured successfully
            bot_logger.debug("Basic configuration done. We are now continuing with...")

        return self.bot


# Bot one common instance
bot = PytmbotInstance().build_bot_instance()
