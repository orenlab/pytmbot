#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from time import sleep

import requests.exceptions

from app import (
    __version__,
    __repository__,
    bot,
    bot_logger,
    telebot,
)
from app.core.handlers.handlers_aggregator import HandlersAggregator
from app.core.middleware.auth import AllowedUser


class PyTMBot:
    """Main PyTMBot class"""

    def __init__(self):
        """
        Initialize the PyTMBot instance.

        This method initializes the PyTMBot instance with the necessary attributes and dependencies.
        It sets the bot instance, handler instance, and sleep time.

        Returns:
            None
        """
        # Set the bot instance
        self.bot = bot

        # Initialize the HandlersAggregator with the bot instance
        self.handler = HandlersAggregator(self.bot)

        # Set the initial sleep duration to 0
        self.sleep_duration = 0

    def __poll_bot_for_updates(self):
        """
        Poll the bot for updates indefinitely.

        This method sets the timeout and long polling timeout for the bot's polling. It also sets whether to skip pending updates.
        The logger level is set to the current logger level.

        Returns:
            None
        """
        # Set the timeout for the bot's polling
        timeout_seconds = 60

        # Set the long polling timeout for the bot's polling
        long_polling_timeout_seconds = 60

        # Set whether to skip pending updates
        skip_pending_updates = True

        # Set the logger level to the current logger level
        logger_level = bot_logger.level

        # Poll the bot for updates indefinitely
        self.bot.infinity_polling(
            timeout=timeout_seconds,
            long_polling_timeout=long_polling_timeout_seconds,
            skip_pending=skip_pending_updates,
            logger_level=logger_level
        )

    def __stop_polling(self, error):
        """
        Stop bot polling on error.

        This method stops the bot polling process when an error occurs. It logs the error message
        and retries after the sleep duration.

        Args:
            error (Exception): The error that caused the polling to stop.
        """
        self.bot.stop_polling()
        bot_logger.error(f'Failed with error: {error}. Retrying after {self.sleep_duration} seconds')
        sleep(self.sleep_duration)

    def __start_polling(self):
        """
        Start bot polling.

        This method continuously polls for updates from the bot until it is stopped.
        It increases the sleep duration by 5 seconds after each attempt.
        If a connection error or a Telegram API exception occurs, it stops polling and retries after the sleep duration.
        If any other unexpected error occurs, it stops polling and logs the error.

        """
        while True:
            # Increase sleep duration by 5 seconds
            self.sleep_duration += 5

            # Log the start of a polling session
            bot_logger.info('Start polling session')

            try:
                # Poll for updates
                self.__poll_bot_for_updates()
            except (requests.exceptions.ConnectionError, telebot.apihelper.ApiTelegramException) as error:
                # Stop polling and retry after the sleep duration
                self.__stop_polling(error)
            except Exception as unexpected_error:
                # Stop polling and log the unexpected error
                self.__stop_polling(unexpected_error)

            # Break the loop after the first iteration
            break

    @staticmethod
    def __log_startup() -> None:
        """
        Log the bot startup.

        This method logs the startup information of the bot, including the version and repository.

        Returns:
            None
        """
        # Log the startup information
        bot_logger.info(f"New instance started! PyTMBot {__version__} ({__repository__})")

    def __setup_middleware(self, middleware) -> None:
        """
        Set up the middleware for the bot.

        This function adds the provided middleware to the bot.

        Args:
            middleware (BaseMiddleware): The middleware to be added to the bot.

        Returns:
            None
        """
        # Add the middleware to the bot
        self.bot.setup_middleware(middleware)

    def run_bot(self):
        """
        Run the bot.

        This function initializes the bot's handlers, logs the startup, and starts
        polling for updates. If any exception occurs during the process, it logs
        the error.

        Raises:
            None

        Returns:
            None
        """
        try:
            # Initialize the AllowedUser middleware
            allowed_user = AllowedUser()

            # Set up the middleware
            self.__setup_middleware(allowed_user)

            # Run the bot's handlers
            self.handler.run_handlers()

            # Log the startup
            self.__log_startup()

            # Start polling for updates
            self.__start_polling()
        except Exception as error:
            # Log the error if any exception occurs
            bot_logger.error(f"Failed at @{__name__}: {error}")


if __name__ == "__main__":
    # Run bot!
    PyTMBot().run_bot()
