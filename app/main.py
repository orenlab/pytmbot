#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from time import sleep

from requests.exceptions import ConnectionError

from app import (
    __version__,
    __repository__,
    bot,
    telebot,
)
from app.core.handlers.handlers_aggregator import HandlersAggregator
from app.core.logs import bot_logger
from app.core.middleware.auth import AllowedUser


def _log_error(error):
    """
    Log the error.
    """
    bot_logger.error(f"Failed at @{__name__}: {error}")


class PyTMBot:
    """
    Main PyTMBot class.

    This class initializes the PyTMBot instance with a bot object,
    a handler object, and a sleep time.
    """

    def __init__(self):
        """
        Initialize the PyTMBot class.

        This method initializes the PyTMBot instance with a bot object,
        a handler object, and a sleep time.
        """
        # Initialize the bot object
        self.bot = bot

        # Initialize the handler object with the bot object
        self.handler = HandlersAggregator(self.bot)

        # Set the sleep time to 0
        self.sleep_time: int = 0

    def _start_polling(self):
        """
        Start bot polling and handle exceptions.

        This method continuously polls the bot for updates and handles any exceptions that occur.
        It increases the sleep time, logs the start of polling, and then calls the `infinity_polling`
        method of the bot object. It sets the timeout and long polling timeout to 60 seconds,
        skips pending updates, and sets the logger level to the level of the bot logger.

        If a `ConnectionError` occurs, it calls the `_handle_connection_error` method.
        If a `telebot.apihelper.ApiTelegramException` occurs, it calls the `_handle_telegram_api_exception` method.
        If any other exception occurs, it calls the `_handle_unexpected_exception` method.

        The method breaks out of the loop after handling the exception.
        """
        while True:
            try:
                self._increase_sleep_time()
                self._log_start_polling()
                self.bot.infinity_polling(
                    timeout=60,
                    long_polling_timeout=60,
                    skip_pending=True,
                    logger_level=bot_logger.level
                )
            except ConnectionError:
                self._handle_connection_error()
            except telebot.apihelper.ApiTelegramException as e:
                self._handle_telegram_api_exception(e)
            except Exception as e:
                self._handle_unexpected_exception(e)
            break

    def _increase_sleep_time(self):
        """
        Increase the sleep time by 5 seconds.

        This function increases the value of the `sleep_time` attribute by 5 seconds.
        """
        self.sleep_time += 5

    @staticmethod
    def _log_start_polling():
        """
        Logs a message indicating the start of a polling session.

        This function logs a message using the `bot_logger` object, indicating that
        a polling session has started.
        """
        # Log a message indicating the start of a polling session
        bot_logger.info('Start polling session')

    def _handle_connection_error(self):
        """
        Handle a connection error by stopping polling, logging an error message,
        and sleeping for a specified period of time.

        Args:
            self: The instance of the class.

        Returns:
            None
        """
        # Stop polling
        self.bot.stop_polling()

        # Log an error message
        error_message = f'Connection failed. Retry after {self.sleep_time} seconds'
        bot_logger.error(error_message)

        # Sleep for the specified period of time
        sleep(self.sleep_time)

    def _handle_telegram_api_exception(self, e):
        """
        Handle a Telegram API exception by stopping polling, logging an error message,
        and sleeping for a specified period of time.

        Args:
            e (telebot.apihelper.ApiTelegramException): The exception object.

        Returns:
            None
        """
        # Stop polling
        self.bot.stop_polling()

        # Log an error message with the exception and the sleep time
        error_message = f'{e}. Retry after {self.sleep_time} seconds.'
        bot_logger.error(error_message)

        # Sleep for the specified period of time
        sleep(self.sleep_time)

    def _handle_unexpected_exception(self, e):
        """
        Handles an unexpected exception by stopping polling, logging an error message,
        and unable to perform an automatic restart.

        Args:
            e (Exception): The exception object.

        Returns:
            None
        """
        # Stop polling to prevent further handling of incoming updates
        self.bot.stop_polling()

        # Log an error message with the exception details
        error_message = f"Unexpected exception: {e}"
        bot_logger.error(error_message)

    def run_bot(self):
        """
        Run the bot and setup middleware, handlers, and start polling process.

        This method sets up the necessary middleware, handlers, and logs the start of the instance.
        It then starts the polling process to listen for incoming updates.

        Raises:
            ConnectionError: If there is a connection error.
            ImportError: If there is an import error.
            AttributeError: If there is an attribute error.
        """
        try:
            # Setup middleware
            self._setup_middleware()

            # Run handlers
            self._run_handlers()

            # Log the start of the instance
            self._log_start()

            # Start polling process
            self.__start_polling()
        except (ConnectionError, ImportError, AttributeError) as e:
            # Log any exceptions that occur
            _log_error(e)

    def _setup_middleware(self):
        """
        Set up middleware with an instance of AllowedUser.

        This method initializes the middleware by setting the bot message template
        and the update types.

        Returns:
            None
        """
        # Create an instance of the AllowedUser middleware
        middleware = AllowedUser()

        # Set up the middleware with the instance
        self.bot.setup_middleware(middleware)

    def _run_handlers(self):
        """
        Run the handlers.

        This method runs the handlers by calling the `run_handlers` method of the `handler` object.

        Returns:
            None
        """
        # Call the run_handlers method of the handler object
        self.handler.run_handlers()

    def __start_polling(self):
        """
        Start the polling process for the bot.

        This method calls the `polling` method of the `bot` object to start the polling process.
        The bot will continuously listen for incoming updates and process them accordingly.

        Raises:
            ConnectionError: If there is a connection error while polling.
            ImportError: If there is an import error while polling.
            AttributeError: If there is an attribute error while polling.
        """
        try:
            # Start the polling process
            self.bot.polling()
        except (ConnectionError, ImportError, AttributeError) as e:
            # Log any exceptions that occur
            _log_error(e)

    @staticmethod
    def _log_start():
        """
        Log the start of the instance.

        This method logs a message indicating the start of a new instance of the PyTMBot.
        It includes the version and repository information.

        Returns:
            None
        """
        # Log a message indicating the start of a new instance
        bot_logger.info(f"New instance started! PyTMBot {__version__} ({__repository__})")


if __name__ == "__main__":
    # Run bot!
    PyTMBot().run_bot()
