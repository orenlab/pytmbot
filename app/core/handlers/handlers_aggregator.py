#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
import concurrent.futures

from app.core.handlers import __all_handlers__
from app.core.logs import bot_logger


class HandlersAggregator:
    """
    Class for aggregating and initializing all the handlers for the bot.

    Attributes:
        bot (telegram.Bot): The bot instance.
    """

    def __init__(self, bot_instance):
        """
        Initialize the HandlersAggregator instance.

        Args:
            bot_instance (telebot.Telebot): The bot instance.

        This method initializes the HandlersAggregator instance with the provided bot instance.
        It assigns the bot instance to the bot attribute and initializes all handler instances.

        Returns:
            None
        """
        # Assign the bot instance to the bot attribute
        self.bot = bot_instance

        # Initialize all handler instances
        self.handlers = [*map(lambda handler: handler(self.bot), __all_handlers__)]

    def run_handlers(self):
        """
        Run all handlers concurrently using threading.

        This method creates a thread for each handler to run concurrently.
        It captures any exceptions that occur during the handling process.

        Raises:
            None
        """

        # Log the start of the handlers run
        bot_logger.debug("Starting handlers initialization...")

        # Initialize the handlers counter
        handlers_count = len(self.handlers)

        try:
            # Create a thread pool executor with the number of handlers
            with concurrent.futures.ThreadPoolExecutor(max_workers=handlers_count) as executor:
                # Submit the handle method of each handler to the executor
                futures = [executor.submit(handler.handle) for handler in self.handlers]

                # Wait for all the futures to complete
                concurrent.futures.wait(futures)
        except Exception as e:
            # Log any exceptions that occur during the handlers run
            bot_logger.error(f"Failed at @{self.__class__.__name__} whit error: {e}")

        # Log the successful completion of the handlers run
        bot_logger.debug("Handlers instance initialization successful.")
        bot_logger.debug(f"Setup bot instances successful with {handlers_count} handlers.")
