#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

import abc

from app import (
    config,
    exceptions,
    bot_logger
)
from app.core.adapters.psutil_adapter import PsutilAdapter
from app.core.jinja2.jinja2 import Jinja2Renderer, TemplateError
from app.core.keyboards.keyboards import Keyboard
from app.core.settings.loggers import MessageTpl
from app.utilities.utilities import (
    get_emoji,
    round_up_tuple,
)


class Handler(metaclass=abc.ABCMeta):
    """Abstract base class for handlers"""

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

    @abc.abstractmethod
    def handle(self):
        """Main abstract method"""

    def _send_bot_answer(self, chat_id, **kwargs) -> None:
        """Send the bot answer"""
        try:
            self.bot.send_message(
                chat_id,
                **kwargs
            )
        except ConnectionError:
            bot_logger.error("Connection error")
