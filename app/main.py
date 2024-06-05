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
    telebot,
)
from app.core.handlers.handlers_aggregator import HandlersAggregator
from app.core.logs import bot_logger
from app.core.middleware.auth import AllowedUser


def _log_startup_message():
    """
    Log the startup message for the bot.

    This function logs a message indicating that a new instance of the bot has started.
    The message includes the version and repository information of the bot.

    Returns:
        None
    """
    # Log the startup message
    bot_logger.info(f"New instance started! PyTMBot {__version__} ({__repository__})")


def _log_error(message: str) -> None:
    """
    Log an error message for the bot.

    Args:
        message (str): The error message to log.

    Returns:
        None
    """
    # Log the error message using the bot logger.
    # The exc_info parameter is set False to avoid logging the full traceback.
    bot_logger.error(message, exc_info=False)


class PyTMBot:
    """
    Main PyTMBot class.

    This class represents the main PyTMBot instance and initializes it with
    the necessary dependencies.
    """

    def __init__(self):
        """
        Initialize the PyTMBot instance.

        This method initializes the PyTMBot instance by setting the bot instance,
        initializing the handlers aggregator, and setting the sleep time to 0.

        Args:
            self: The PyTMBot instance.

        Returns:
            None
        """
        # Set the bot instance
        self.bot = bot  # Assuming 'bot' is a valid bot instance

        # Initialize the handlers aggregator
        self.handler = HandlersAggregator(self.bot)
        """
        The handlers aggregator instance. It aggregates and initializes all the
        handlers for the bot.
        """

        # Set the sleep time to 0
        self.sleep_time: int = 0
        """
        The sleep time in seconds. It is set to 0 by default.
        """

    def __start_polling(self):
        """
        Continuously poll the bot for updates until an exception occurs.
        If a ConnectionError or ApiTelegramException is raised, the bot is stopped and the function retries after a
        certain time. If any other exception occurs, the bot is also stopped and an error message is logged.

        Raises:
            ConnectionError: If the connection to the Telegram API fails.
            ApiTelegramException: If there is an issue with the Telegram API.
            Exception: If any other unexpected exception occurs.
        """
        while True:
            try:
                self.sleep_time += 5
                self._log_start_of_polling_session()
                self.__poll_bot_for_updates()
            except (requests.exceptions.ConnectionError, telebot.apihelper.ApiTelegramException) as e:
                self.__handle_connection_error(e, sleep_time=self.sleep_time)
                sleep(self.sleep_time)
                continue
            except Exception as e:
                self.__handle_unexpected_error(e)
                sleep(self.sleep_time)
                continue
            else:
                break

    @staticmethod
    def _log_start_of_polling_session():
        """
        Logs the start of a polling session.

        This method is a static method that logs the start of a polling session. It uses the `bot_logger` to log an
        informational message indicating that the polling session has started.

        This method does not take any parameters and does not return anything.
        """
        # Log the start of the polling session
        bot_logger.info('Start polling session')

    def __poll_bot_for_updates(self):
        """
        Poll the bot for updates with specified timeout and logging level.

        This function uses the `infinity_polling` method of the `bot` object to continuously
        check for updates. The timeout and long polling timeout are set to 60 seconds, and
        the `skip_pending` parameter is set to True to skip pending updates. The logging
        level is set to the current logging level of the `bot_logger`.

        Returns:
            None
        """
        # Set the timeout for checking for updates
        timeout = 60

        # Set the long polling timeout
        long_polling_timeout = 60

        # Skip pending updates
        skip_pending = True

        # Set the logging level to the current logging level of the bot_logger
        logger_level = bot_logger.level

        # Poll the bot for updates
        self.bot.infinity_polling(
            timeout=timeout,
            long_polling_timeout=long_polling_timeout,
            skip_pending=skip_pending,
            logger_level=logger_level
        )

    def __handle_connection_error(self, e, sleep_time):
        """
        Handle connection error by stopping polling, logging the error message,
        and indicating the time to retry.

        Args:
            e (Exception): The connection error that occurred.
            sleep_time (int): The time in seconds to wait before retrying.
        """
        # Stop polling to avoid further errors
        self.bot.stop_polling()

        # Log the error message with the sleep time
        bot_logger.debug(f"{e}. Retry after {sleep_time} seconds")

        # Log the error message with the sleep time
        _log_error(f'Failed at @{__name__}: Connection error. Retry after {sleep_time} seconds')

    def __handle_unexpected_error(self, e):
        """
        Handle unexpected errors by stopping polling, logging the error message,
        and indicating that an automatic restart is not possible.

        Args:
            e (Exception): The unexpected error that occurred.
        """
        # Stop polling to avoid further errors
        self.bot.stop_polling()

        # Log the error message with the error details
        bot_logger.debug(f"Failed: {e}.")

        # Log a generic error message indicating that an automatic restart is not possible
        _log_error("Unexpected exception.")

    def run_bot(self):
        """
        Run the bot and handle exceptions.

        This method initializes the bot, sets up middleware, runs handlers,
        logs the startup message, and starts polling for updates.
        It handles ConnectionError and ImportError exceptions by logging the errors.

        Raises:
            ConnectionError: If the connection to the Telegram API fails.
            ImportError: If there is an issue importing a required module.
        """
        try:
            self.__setup_middleware()  # Set up middleware for the bot
            self.__run_handlers()  # Run the handlers for the bot
            _log_startup_message()  # Log the startup message
            self.__start_polling()  # Start polling for updates from the bot
        except ConnectionError as e:
            _log_error(f"Failed at @{__name__}: {e}")  # Log the connection error
        except ImportError as e:
            _log_error(f"Failed: cannot import name {e}")  # Log the import error

    def __setup_middleware(self):
        """
        Setup middleware for the bot.

        This method initializes the middleware for the bot by creating an instance of the AllowedUser class
        and passing it to the bot's setup_middleware method.
        """
        # Create an instance of the AllowedUser class
        allowed_user = AllowedUser()

        # Set up the middleware for the bot by passing the instance of AllowedUser to the bot's setup_middleware method
        self.bot.setup_middleware(allowed_user)

    def __run_handlers(self):
        """
        Run the handlers for the bot.

        This method calls the `run_handlers` method of the `HandlersAggregator` instance.
        """
        self.handler.run_handlers()


if __name__ == "__main__":
    # Run bot!
    PyTMBot().run_bot()
