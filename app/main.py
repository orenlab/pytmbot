#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from time import sleep
from typing import Union, Optional

from requests.exceptions import ReadTimeout, ConnectionError
from urllib3.exceptions import ReadTimeoutError

from app import PyTMBotInstance
from app import (
    __version__,
    __repository__,
    bot_logger,
    telebot,
)
from app.core.handlers.handlers_aggregator import HandlersAggregator
from app.core.middleware.auth import AllowedUser


class PyTMBot(PyTMBotInstance):
    """
    Main PyTMBot class.

    This class initializes the bot instance and the HandlersAggregator with the bot instance.
    It also sets the initial sleep duration to 0.
    """

    def __init__(self):
        """
        Initialize the PyTMBot instance.

        This method initializes the bot instance and the HandlersAggregator with the bot instance.
        It also sets the initial sleep duration to 0.
        """
        super().__init__()

        # Set the bot instance
        self.bot = self.get_bot_instance()

        # Initialize the HandlersAggregator with the bot instance
        self.handler = HandlersAggregator(self.bot)

        # Set the initial sleep duration to 0
        self.sleep_duration = 0

    def __poll_bot_for_updates(self):
        """
        Poll the bot for updates indefinitely.

        This method sets the timeout and long polling timeout for the bot's polling. It also sets whether to skip
        pending updates. The logger level is set to the current logger level.

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

    def __stop_polling(self, error: Union[Exception, str],
                       sleep_duration: Optional[int] = 0) -> bool:
        """
        Stop bot polling and log the error.

        Args:
            error (Union[Exception, str]): The error that occurred.
            sleep_duration (int, optional): The duration to sleep before retrying.
                                            Defaults to 0.

        Returns:
            bool: True if the bot polling has been stopped.
        """
        # Stop the bot from polling for updates
        self.bot.stop_polling()

        # Determine the log level and message based on the error type
        if isinstance(error, Exception):
            # Log level for exceptions
            log_level = 'error'
            # Log message for exceptions
            log_message = f'Failed with error: {error}. Retrying after {sleep_duration} seconds'
        else:
            # Log level for connection errors
            log_level = 'debug' if bot_logger.level == 10 else 'error'
            # Log message for connection errors
            log_message = f'Failed with error: Connection error. Retrying after {sleep_duration} seconds'

        # Log the error with the duration before retrying
        getattr(bot_logger, log_level)(log_message)

        # Sleep for the specified duration
        sleep(sleep_duration)

        return True

    def __start_polling(self) -> None:
        """
        Start polling for updates from the bot.

        This function runs in a loop, polling for updates from the bot. It increases the sleep duration by 5 seconds
        after each iteration. If an error occurs during polling, it logs the error and retries after the sleep duration.
        If an unexpected error occurs, it logs the error and stops polling.

        Returns:
            None
        """

        while True:
            # Increase sleep duration by 5 seconds
            self.sleep_duration += 5

            # Log the start of a polling session
            bot_logger.info('Start polling session............')

            try:
                # Poll for updates
                self.__poll_bot_for_updates()
            except (
                    ReadTimeoutError,
                    ConnectionError,
                    ReadTimeout,
                    telebot.apihelper.ApiTelegramException
            ) as error:
                # Stop polling and retry after the sleep duration
                self.__stop_polling(error, self.sleep_duration)
                continue
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

        Args:
            middleware (BaseMiddleware): The middleware to be added to the bot.

        Returns:
            None

        This function sets up the provided middleware for the bot. It logs the setup process and handles any exceptions
        that may occur.

        """
        # Log the start of the setup process
        bot_logger.debug("Setting up middleware...")

        # Log the middleware that is being set up
        bot_logger.debug(f"Middleware: {middleware.__class__.__name__}")

        try:
            # Add the middleware to the bot
            self.bot.setup_middleware(middleware)

            # Log the successful setup of the middleware
            bot_logger.debug("Middleware setup successful.")
        except Exception as e:
            # Log any errors that occur during the setup process
            bot_logger.debug(f"Error setting up middleware: {e}")

    def run_bot(self):
        """
        Run the bot.

        This function initializes the bot's handlers, logs the startup, and starts
        polling for updates. If any exception occurs during the process, it logs
        the error.

        Raises:
            Exception: If an error occurs during the process.

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
    # Run the bot
    PyTMBot().run_bot()

