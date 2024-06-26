#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTeleMonBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from .about_bot import AboutBotHandler
from .check_bot_update import BotUpdatesHandler
from .containers_handler import ContainersHandler
from .echo import EchoHandler
from .fs_handler import FileSystemHandler
from .load_avg_handler import LoadAvgHandler
from .memory_handler import MemoryHandler
from .net_io_stat import NetIOHandler
from .process_handler import ProcessHandler
from .sensors_handler import SensorsHandler
from .start_handler import StartHandler
from .uptime_handlers import UptimeHandler

__all_defaults_handlers__ = [
    AboutBotHandler,
    BotUpdatesHandler,
    ContainersHandler,
    EchoHandler,
    FileSystemHandler,
    LoadAvgHandler,
    MemoryHandler,
    NetIOHandler,
    ProcessHandler,
    SensorsHandler,
    StartHandler,
    UptimeHandler
]
