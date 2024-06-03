#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from telebot.apihelper import ApiTelegramException

from app import (
    config,
    exceptions,
)
from app.core.adapters.psutil_adapter import PsutilAdapter
from app.core.jinja2.jinja2 import Jinja2Renderer, TemplateError
from app.core.keyboards.keyboards import Keyboard
from app.core.logs import bot_logger
from app.core.settings.loggers import MessageTpl
from app.utilities.utilities import (
    get_emoji,
    round_up_tuple,
)


class HandlerConstructor:
    """Base class for handlers"""

    def __init__(self, bot):
        """Initialize the handler class"""
        self.bot = bot
        self.keyboard = Keyboard()
        self.bot_msg_tpl = MessageTpl()
        self.config = config
        self.jinja = Jinja2Renderer()
        self.TemplateError = TemplateError
        self.exceptions = exceptions
        self.get_emoji = get_emoji
        self.round_up_tuple = round_up_tuple
        self.psutil_adapter = PsutilAdapter()

    def _send_bot_answer(self, *args, **kwargs) -> None:
        """Send the bot answer"""
        try:
            self.bot.send_message(
                *args,
                **kwargs
            )
        except (ConnectionError, ApiTelegramException) as e:
            bot_logger.error(f"Failed at @{__name__}: {e}")
