#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from pytmbot.adapters.psutil.adapter import PsutilAdapter
from pytmbot.keyboards.keyboards import Keyboards
from pytmbot.middleware.session_manager import SessionManager
from pytmbot.settings import settings, log_settings, var_config
from pytmbot.utils.utilities import EmojiConverter

# pyTMbot globals initialization

# Set global namespace
__version__ = 'v2.0.0-dev-alpha.2'
__author__ = 'Denis Rozhnovskiy <pytelemonbot@mail.ru>'
__license__ = 'MIT'
__repository__ = 'https://github.com/orenlab/pytmbot'
__github_api_url__ = 'https://api.github.com/repos/orenlab/pytmbot/releases/latest'

# Settings from pytmbot.yaml
settings = settings
# Bot variable config
var_config = var_config
# Session manager
session_manager = SessionManager()
# Logs settings
log_settings = log_settings
# Keyboard
keyboards = Keyboards()
# EmojiConverter
em = EmojiConverter()
# psutil adapter
psutil_adapter = PsutilAdapter()
