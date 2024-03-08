#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

import abc
# ------------------------------------------
# Deprecated in next release. Move to psutil
from app.core.glances import GlancesPoller
# !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
# ------------------------------------------
from app.core.keyboards.keyboards import Keyboard
from app.core.settings.message_tpl import MessageTpl
from app import (
    config,
    exceptions
)
from app.core.jinja2.jinja2 import Jinja2Renderer, TemplateError
from app.utilities.utilities import (
    get_emoji,
    round_up_tuple,
    format_bytes,
    split_str,
    replace_symbol
)


class Handler(metaclass=abc.ABCMeta):
    """
    Abstract base class for handlers
    """

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
        self.format_bytes = format_bytes
        self.split_str = split_str
        self.replace_symbol = replace_symbol
        self.api_data = GlancesPoller()

    @abc.abstractmethod
    def handle(self):
        """Abstract method"""
        pass
