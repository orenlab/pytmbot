#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from functools import lru_cache

import telebot

from app.core import exceptions
from app.core.logs import bot_logger
from app.core.settings.bot_settings import BotSettings
from app.utilities.utilities import parse_cli_args

# Main config
config = BotSettings()

# Set global name
__version__ = 'v0.1.0-pre-release'
__author__ = 'Denis Rozhnovskiy <pytelemonbot@mail.ru>'
__license__ = 'MIT'
__repository__ = 'https://github.com/orenlab/pytmbot'
__github_api_url__ = 'https://api.github.com/repos/orenlab/pytmbot/releases/latest'


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

        This method checks if the instance of the TeleBot is already created.
        If not, it creates a new instance of the PyTMBotInstance and sets up the bot token.
        It also logs the bot token and performs a test to check if the bot token is valid.
        If the bot token is not valid, it raises a PyTeleMonBotError.
        If the connection to the Telegram API fails, it raises a PyTeleMonBotError.
        After the basic configuration is done, it adds the ContainersCallbackFilter to the TeleBot.

        Returns:
            telebot.TeleBot: The instance of the TeleBot.

        Raises:
            exceptions.PyTeleMonBotError: If the bot token is not valid.
        """

        # Check if the instance of the TeleBot is already created
        if not PyTMBotInstance._instance:
            # Create a new instance of the PyTMBotInstance
            PyTMBotInstance._instance = PyTMBotInstance()

            try:
                # Get the bot token
                bot_token = PyTMBotInstance._instance.__get_bot_token()
            except (FileNotFoundError, ValueError) as error:
                # Raise a PyTeleMonBotError if the bot token is not valid
                raise exceptions.PyTeleMonBotError(".pytmbotenv file is not valid or not found") from error

            # Log the bot token
            bot_logger.debug("Bot token setup successful")

            # Create a new instance of the TeleBot
            PyTMBotInstance._instance.bot = telebot.TeleBot(
                token=bot_token,
                use_class_middlewares=True,
                exception_handler=exceptions.TelebotCustomExceptionHandler(),
            )

            # Log the bot token
            bot_logger.debug("Now we need to test the bot token...")

            try:
                # Test the bot token
                test_bot = PyTMBotInstance._instance.bot.get_me()
            except (telebot.apihelper.ApiTelegramException, ConnectionError) as error:
                # Raise a PyTeleMonBotError based on the specific exception
                if isinstance(error, telebot.apihelper.ApiTelegramException):
                    error_message = "Bot token is not valid. Please check the token and try again."
                else:
                    error_message = "Connection to the Telegram API failed."
                raise exceptions.PyTeleMonBotError(error_message) from error

            # Log that the bot token is valid
            bot_logger.debug("Bot token is valid.")
            bot_logger.debug(f"Bot info: {test_bot}.")

            # Define the list of bot commands
            commands = [telebot.types.BotCommand(command, desc) for command, desc in config.bot_commands.items()]

            # Set the bot commands
            PyTMBotInstance._instance.bot.set_my_commands(commands)

            bot_logger.debug(f"Bot commands setup successful with {len(commands)} commands.")

            # Log that the bot has been configured successfully
            bot_logger.debug("Basic configuration done. We are now continuing with...")

        # Return the instance of the TeleBot
        return PyTMBotInstance._instance.bot


PyTMBotInstance._instance = None
