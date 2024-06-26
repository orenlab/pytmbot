#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
import multiprocessing as mp

from app.core.handlers.default_handlers import __all_defaults_handlers__
from app.core.handlers.inline_handlers import __all_inline_handlers__
from app.core.logs import bot_logger


class HandlersAggregator:
    """
    Class for aggregating and initializing all the handlers for the bot.

    Attributes:
        bot (telegram.Bot): The bot instance.
        handlers (list): The list of handler instances.
    """

    def __init__(self, bot_instance):
        """
        Initialize the HandlersAggregator instance.

        Args:
            bot_instance (telegram.Bot): The bot instance.
        """
        # Assign the bot instance to the bot attribute
        self.bot = bot_instance

        # Initialize all handler instances
        self.handlers = [handler(self.bot) for handler in [
            *__all_inline_handlers__,
            *__all_defaults_handlers__
        ]]

    def run_handlers(self):
        """
        Run all handlers using multiprocessing.

        This method spawns a process for each handler to run concurrently.
        It captures any exceptions that occur during the handling process.

        Raises:
            None
        """

        # Log the start of the handlers run
        bot_logger.debug("Starting handlers initialization...")

        # Initialize the handlers counter
        handlers_count = 0

        # Create a multiprocessing pool
        with mp.Pool() as pool:
            # Apply async to each handler
            for handler in self.handlers:
                # Apply the handler's handle method in a separate process
                # and capture any exceptions
                pool.apply_async(
                    handler.handle(),
                    error_callback=self._log_error
                )

                bot_logger.debug(f"Initialized handler: {handler.__class__.__name__}.")

                # Increment the handlers counter
                handlers_count += 1

        # Close the pool to prevent any more work
        pool.close()

        # Block until all tasks are done
        pool.join()

        # Log the successful completion of the handlers run
        bot_logger.debug("Handlers instance initialization successful.")
        bot_logger.debug(f"Setup bot instances successful with {handlers_count} handlers.")

    @staticmethod
    def _log_error(e):
        """
        Log an exception that occurred during the handling process.

        Args:
            e (Exception): The exception that occurred.

        This function logs the exception that occurred during the handling process.
        It uses the bot_logger to log the error message, which includes the module
        name and the string representation of the exception.
        """
        # Log the error message
        bot_logger.error(f"Failed at @{__class__.__name__} with error: {str(e)}.")
