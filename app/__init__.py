#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

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
__version__ = 'v0.1.0-dev-20240620'
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

    Methods:
        build_bot_instance()

    Raises:
        ValueError: If the provided mode is invalid.

    Example:
        bot = PytmbotInstance().build_bot_instance()
        bot.polling()
    """

    def __init__(self):
        """
        Initializes the object by setting the `bot` attribute to None.

        This attribute is used to store an instance of the bot object.
        """
        self.bot = None

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
            # Log that the bot instance is being built
            bot_logger.debug("Building bot instance...")

            # Get the bot mode from the command line arguments
            bot_mode = parse_cli_args()

            # Log the bot mode
            bot_logger.debug(f"Bot mode: {bot_mode.mode}")

            # Get the bot token based on the bot mode
            bot_token = (
                config.dev_bot_token.get_secret_value()  # Get dev bot token if mode is 'dev'
                if bot_mode.mode == "dev"
                else config.bot_token.get_secret_value()  # Get regular bot token otherwise
            )

            # Log that the bot token has been successfully received
            bot_logger.debug(f"The bot token has been successfully received.")

            # Create a new TeleBot instance with the bot token and custom middleware
            self.bot = telebot.TeleBot(
                token=bot_token,
                use_class_middlewares=True,
                exception_handler=exceptions.TelebotCustomExceptionHandler(),
            )

            # Add a custom filter for callback queries to the bot
            self.bot.add_custom_filter(ContainersCallbackFilter())

            bot_logger.debug("Filters added successfully.")

            # Log that the bot has been configured successfully
            bot_logger.debug(f"Bot configured successfully.")

        return self.bot


# Bot one common instance
bot = PytmbotInstance().build_bot_instance()
