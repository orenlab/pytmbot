#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTeleMonBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from app.core.handlers.default_handlers.fs_handler import FileSystemHandler
from app.core.handlers.default_handlers.containers_handler import ContainersHandler
from app.core.handlers.default_handlers.process_handler import ProcessHandler
from app.core.handlers.default_handlers.uptime_handlers import UptimeHandler
from app.core.handlers.default_handlers.start_handler import StartHandler
from app.core.handlers.default_handlers.sensors_handler import SensorsHandler
from app.core.handlers.default_handlers.memory_handler import MemoryHandler
from app.core.handlers.default_handlers.load_avg_handler import LoadAvgHandler
