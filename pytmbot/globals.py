#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from pytmbot.adapters.psutil.adapter import PsutilAdapter
from pytmbot.keyboards.keyboards import Keyboards, ButtonData
from pytmbot.middleware.session_manager import SessionManager
from pytmbot.settings import (
    settings as app_settings,
    var_config as app_var_config,
    bot_command_settings as app_bot_command_settings,
    bot_description_settings as app_bot_description_settings,
)
from pytmbot.utils import EmojiConverter, is_running_in_docker

# pyTMBot globals initialization

# Global namespace information
__version__ = "0.2.2"
__author__ = "Denis Rozhnovskiy <pytelemonbot@mail.ru>"
__license__ = "MIT"
__repository__ = "https://github.com/orenlab/pytmbot"
__github_api_url__ = "https://api.github.com/repos/orenlab/pytmbot/releases/latest"

# Settings from pytmbot.yaml
settings = app_settings
# Bot variable config
var_config = app_var_config
# Session manager
session_manager = SessionManager()
# Bot commands
bot_commands_settings = app_bot_command_settings
# Bot description
bot_description_settings = app_bot_description_settings
# Keyboard
keyboards = Keyboards()
# EmojiConverter
em = EmojiConverter()
# ButtonData
button_data = ButtonData
# psutil adapter
psutil_adapter = PsutilAdapter()
# Running in docker
running_in_docker = is_running_in_docker()
