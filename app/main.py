#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from time import sleep

from requests.exceptions import (
    ReadTimeout,
    HTTPError,
    ConnectionError,
    BaseHTTPError)

from app import (
    __version__,
    __repository__,
    bot,
    telebot,
)
from app.core.handlers.handlers_aggregator import HandlersAggregator
from app.core.logs import bot_logger
from app.core.middleware.auth import AllowedUser


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
        self.bot = bot  # Initialize the bot object
        self.handler = HandlersAggregator(self.bot)  # Initialize the handler object
        self.sleep_time: int = 0  # Initialize the sleep time to 0

    def _start_polling(self):
        """
        Start bot polling.

        This method continuously polls the bot for updates until an exception is raised.
        If a connection error occurs, the method will retry after a specified sleep time.

        Raises:
            Exception: If an unexpected exception occurs.

        """
        while True:
            try:
                # Increase the sleep time by 5 seconds for each retry
                self.sleep_time += 5
                bot_logger.info('Start polling session')
                self.bot.infinity_polling(
                    timeout=60,
                    long_polling_timeout=60,
                    skip_pending=True,
                    logger_level=bot_logger.level
                )
            except (ReadTimeout, HTTPError, ConnectionError, BaseHTTPError) as e:
                # If a connection error occurs, stop polling and log the error
                self.bot.stop_polling()
                bot_logger.debug(f"{e}. Retry after {self.sleep_time} seconds")
                bot_logger.error(f'Connection failed. Retry after {self.sleep_time} seconds')
                sleep(self.sleep_time)
                continue
            except telebot.apihelper.ApiTelegramException as e:
                # If a Telegram API exception occurs, stop polling and log the error
                self.bot.stop_polling()
                bot_logger.error(f'{e}. Retry after {self.sleep_time} seconds.')
                sleep(self.sleep_time)
                continue
            except Exception as e:
                # If an unexpected exception occurs, stop polling and log the error
                self.bot.stop_polling()
                bot_logger.debug(f"Failed: {e}. Unable to perform an automatic restart.")
                bot_logger.error("Unexpected exception. Unable to perform an automatic restart.")
            break

    def run_bot(self):
        """
        Run the bot.

        This method sets up the middleware, runs the handlers, logs the start of the instance,
        and starts the polling process.

        Raises:
            ConnectionError: If there is a connection error.
            ImportError: If there is an import error.
            AttributeError: If there is an attribute error.
        """
        try:
            # Set up the middleware with an instance of AllowedUser
            self.bot.setup_middleware(AllowedUser())

            # Run the handlers
            self.handler.run_handlers()

            # Log the start of the instance
            bot_logger.info(f"New instance started! PyTMBot {__version__} ({__repository__})")

            # Start the polling process
            self._start_polling()

        except (ConnectionError, ImportError, AttributeError) as e:
            # Log the error
            bot_logger.error(f"Failed at @{__name__}: {e}")


if __name__ == "__main__":
    # Run bot!
    PyTMBot().run_bot()
