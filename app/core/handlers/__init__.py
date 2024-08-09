#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from .auth_handlers.get_qrcode import GetQrcodeHandler
# Imports default handlers
from .auth_handlers.twofa_index import TwoFAStartHandler
from .default_handlers.about_bot import AboutBotHandler
from .default_handlers.back_handler import BackHandler
from .default_handlers.check_bot_update import BotUpdatesHandler
from .default_handlers.containers_handler import ContainersHandler
from .default_handlers.docker_handler import DockerHandler
from .default_handlers.echo import EchoHandler
from .default_handlers.fs_handler import FileSystemHandler
from .default_handlers.images_handler import ImagesHandler
from .default_handlers.load_avg_handler import LoadAvgHandler
from .default_handlers.memory_handler import MemoryHandler
from .default_handlers.net_io_stat import NetIOHandler
from .default_handlers.process_handler import ProcessHandler
from .default_handlers.sensors_handler import SensorsHandler
from .default_handlers.start_handler import StartHandler
from .default_handlers.uptime_handlers import UptimeHandler
# Imports inline handlers
from .inline_handlers.containers_full_info import InlineContainerFullInfoHandler
from .inline_handlers.swap_handler import InlineSwapHandler
from .inline_handlers.update_info import InlineUpdateInfoHandler

# Globals imports for all handlers in the bot
__all_handlers__ = [
    GetQrcodeHandler,
    TwoFAStartHandler,
    AboutBotHandler,
    BotUpdatesHandler,
    ContainersHandler,
    FileSystemHandler,
    LoadAvgHandler,
    MemoryHandler,
    NetIOHandler,
    ProcessHandler,
    SensorsHandler,
    StartHandler,
    UptimeHandler,
    DockerHandler,
    BackHandler,
    ImagesHandler,
    EchoHandler,
    InlineContainerFullInfoHandler,
    InlineSwapHandler,
    InlineUpdateInfoHandler
]
