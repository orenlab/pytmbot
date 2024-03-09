#!/usr/bin/python3
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
    ContainersHandler
)
from app.core.handlers.inline_handlers import InlineQueryHandler
from app.core.handlers.inline_handlers.swap_handler import InlineSwapHandler


class HandlersAggregator:
    def __init__(self, bot):
        self.bot = bot
        self.start_handler = StartHandler(self.bot)
        self.load_avg_handler = LoadAvgHandler(self.bot)
        self.memory_handler = MemoryHandler(self.bot)
        self.sensors_handler = SensorsHandler(self.bot)
        self.process_handler = ProcessHandler(self.bot)
        self.uptime_handler = UptimeHandler(self.bot)
        self.fs_handler = FileSystemHandler(self.bot)
        self.containers_handler = ContainersHandler(self.bot)
        self.inline_query_handler = InlineQueryHandler(self.bot)
        self.inline_swap_handler = InlineSwapHandler(self.bot)

    def run_handlers(self):
        self.start_handler.handle()
        self.load_avg_handler.handle()
        self.memory_handler.handle()
        self.sensors_handler.handle()
        self.process_handler.handle()
        self.uptime_handler.handle()
        self.fs_handler.handle()
        self.containers_handler.handle()
        self.inline_query_handler.handle()
        self.inline_swap_handler.handle()
