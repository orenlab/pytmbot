#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from app.core.handlers.default_handlers import (
    StartHandler,
    LoadAvgHandler,
    MemoryHandler,
    SensorsHandler,
    ProcessHandler,
    UptimeHandler,
    FileSystemHandler,
    ContainersHandler,
    BotUpdatesHandler,
    NetIOHandler,
    AboutBotHandler,
    EchoHandler
)
from app.core.handlers.inline_handlers.swap_handler import InlineSwapHandler
from app.core.handlers.inline_handlers.update_info import InlineUpdateInfoHandler
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
        self.bot = bot_instance
        self.handlers = [
            StartHandler(self.bot),  # Initialize the StartHandler instance
            LoadAvgHandler(self.bot),  # Initialize the LoadAvgHandler instance
            MemoryHandler(self.bot),  # Initialize the MemoryHandler instance
            SensorsHandler(self.bot),  # Initialize the SensorsHandler instance
            ProcessHandler(self.bot),  # Initialize the ProcessHandler instance
            UptimeHandler(self.bot),  # Initialize the UptimeHandler instance
            FileSystemHandler(self.bot),  # Initialize the FileSystemHandler instance
            ContainersHandler(self.bot),  # Initialize the ContainersHandler instance
            BotUpdatesHandler(self.bot),  # Initialize the BotUpdatesHandler instance
            InlineSwapHandler(self.bot),  # Initialize the InlineSwapHandler instance
            InlineUpdateInfoHandler(self.bot),  # Initialize the InlineUpdateInfoHandler instance
            NetIOHandler(self.bot),  # Initialize the NetIOHandler instance
            AboutBotHandler(self.bot),  # Initialize the AboutBotHandler instance
            EchoHandler(self.bot)  # Initialize the EchoHandler instance
        ]

        def run_handlers(self):
            """
            Run all handlers.

            This method iterates over each handler and calls its `handle` method.
            If any handler raises a `ConnectionError` or `ValueError`, it logs the error.
            If any other exception occurs, it logs the error.

            Raises:
                None
            """
            try:
                # Iterate over each handler
                for handler in self.handlers:
                    try:
                        # Call the handle method of the handler
                        handler.handle()
                    except (ConnectionError, ValueError) as e:
                        # Log the error if a ConnectionError or ValueError occurs
                        bot_logger.error(f"Failed at @{__name__}: {str(e)}")
            except Exception as e:
                # Log the error if any other exception occurs
                bot_logger.error(f"Failed at @{__name__}: {str(e)}")
