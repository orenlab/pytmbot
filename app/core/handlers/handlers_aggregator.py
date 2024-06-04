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
        start_handler (StartHandler): Handler for the start command.
        load_avg_handler (LoadAvgHandler): Handler for the load average command.
        memory_handler (MemoryHandler): Handler for the memory command.
        sensors_handler (SensorsHandler): Handler for the sensors command.
        process_handler (ProcessHandler): Handler for the process command.
        uptime_handler (UptimeHandler): Handler for the uptime command.
        fs_handler (FileSystemHandler): Handler for the file system command.
        containers_handler (ContainersHandler): Handler for the containers command.
        bot_updates_handler (BotUpdatesHandler): Handler for the bot updates command.
        inline_swap_handler (InlineSwapHandler): Handler for the inline swap command.
        inline_update_info (InlineUpdateInfoHandler): Handler for the inline update info command.
        net_io_stats_handler (NetIOHandler): Handler for the network I/O stats command.
        about_bot (AboutBotHandler): Handler for the about_bot command.
        echo (EchoHandler): Handler for the echo command.
    """

    def __init__(self, bot):
        """
        Initialize the HandlersAggregator instance.

        Args:
            bot (telegram.Bot): The bot instance.
        """
        self.bot = bot
        self.start_handler = StartHandler(self.bot)  # Initialize the start handler
        self.load_avg_handler = LoadAvgHandler(self.bot)  # Initialize the load average handler
        self.memory_handler = MemoryHandler(self.bot)  # Initialize the memory handler
        self.sensors_handler = SensorsHandler(self.bot)  # Initialize the sensors handler
        self.process_handler = ProcessHandler(self.bot)  # Initialize the process handler
        self.uptime_handler = UptimeHandler(self.bot)  # Initialize the uptime handler
        self.fs_handler = FileSystemHandler(self.bot)  # Initialize the file system handler
        self.containers_handler = ContainersHandler(self.bot)  # Initialize the containers handler
        self.bot_updates_handler = BotUpdatesHandler(self.bot)  # Initialize the bot updates handler
        self.inline_swap_handler = InlineSwapHandler(self.bot)  # Initialize the inline swap handler
        self.inline_update_info = InlineUpdateInfoHandler(self.bot)  # Initialize the inline update info handler
        self.net_io_stats_handler = NetIOHandler(self.bot)  # Initialize the network I/O stats handler
        self.about_bot = AboutBotHandler(self.bot)  # Initialize the about_bot handler
        self.echo = EchoHandler(self.bot)  # Initialize the echo handler

    def run_handlers(self):
        """
        Run all handlers.

        This method iterates over each handler and calls its `handle` method.
        If any handler raises a `ConnectionError` or `ValueError`, it logs the error.
        """
        try:
            # Call handle method for each handler
            self.start_handler.handle()  # Handler for the start command
            self.load_avg_handler.handle()  # Handler for the load average command
            self.memory_handler.handle()  # Handler for the memory command
            self.sensors_handler.handle()  # Handler for the sensors command
            self.process_handler.handle()  # Handler for the process command
            self.uptime_handler.handle()  # Handler for the uptime command
            self.fs_handler.handle()  # Handler for the file system command
            self.containers_handler.handle()  # Handler for the containers command
            self.bot_updates_handler.handle()  # Handler for the bot updates command
            self.net_io_stats_handler.handle()  # Handler for the network I/O stats command
            self.about_bot.handle()  # Handler for the about_bot command
            self.inline_swap_handler.handle()  # Handler for the inline swap command
            self.inline_update_info.handle()  # Handler for the inline update info command
            self.echo.handle()  # Handler for the echo command
        except (ConnectionError, ValueError) as e:
            bot_logger.error(f"Failed at @{__name__}: {str(e)}")
