from pytmbot.adapters.psutil.adapter import PsutilAdapter
from pytmbot.keyboards.keyboards import Keyboards
from pytmbot.middleware.session_manager import SessionManager
from pytmbot.settings import BotSettings, LogsSettings
from pytmbot.utils.utilities import EmojiConverter

# pyTMbot globals initialization

# Set global namespace
__version__ = 'v0.1.2-dev'
__author__ = 'Denis Rozhnovskiy <pytelemonbot@mail.ru>'
__license__ = 'MIT'
__repository__ = 'https://github.com/orenlab/pytmbot'
__github_api_url__ = 'https://api.github.com/repos/orenlab/pytmbot/releases/latest'

# Main config
config = BotSettings()
# Session manager
session_manager = SessionManager()
# Logs settings
log_settings = LogsSettings()
# Keyboard
keyboards = Keyboards()
# EmojiConverter
em = EmojiConverter()
# psutil adapter
psutil_adapter = PsutilAdapter()
