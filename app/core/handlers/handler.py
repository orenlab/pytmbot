#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from app import (
    config,
    exceptions,
)
from app.core.adapters.psutil_adapter import PsutilAdapter
from app.core.jinja2.jinja2 import Jinja2Renderer, TemplateError
from app.core.keyboards.keyboards import Keyboard
from app.core.settings.loggers import MessageTpl
from app.utilities.utilities import (
    EmojiConverter,
    round_up_tuple,
)


class HandlerConstructor:
    """
    Base class for handlers.

    This class initializes the handler with necessary attributes and dependencies.

    Attributes:
        bot (telebot.TeleBot): The Telegram bot instance.
        keyboard (Keyboard): The keyboard object for building reply and inline keyboards.
        bot_msg_tpl (MessageTpl): The message template object for formatting bot messages.
        config (Config): The configuration object containing bot settings.
        jinja (Jinja2Renderer): The Jinja2 renderer object for templating bot messages.
        template_error (TemplateError): The exception class for template errors.
        exceptions (Exceptions): The custom exception class for handling Telegram API errors.
        emojis (function): The utility function for getting emoji by name.
        round_up_tuple (function): The utility function for rounding up tuple values.
        psutil_adapter (PsutilAdapter): The adapter object for interacting with the psutil library.
    """

    def __init__(self, bot):
        """
        Initialize the handler class.

        Args:
            bot (telebot.TeleBot): The Telegram bot instance.

        This method initializes the handler class with necessary attributes and dependencies.
        It sets the bot instance, keyboard, message template, configuration, Jinja2 renderer,
        template error class, custom exception class, utility functions for getting emoji and rounding up tuple values,
        and an adapter for interacting with the psutil library.
        """
        # Set the bot instance
        self.bot = bot

        # Initialize the keyboard object for building reply and inline keyboards
        self.keyboard = Keyboard()

        # Initialize the message template object for formatting bot messages
        self.bot_msg_tpl = MessageTpl()

        # Set the configuration object containing bot settings
        self.config = config

        # Initialize the Jinja2 renderer object for templating bot messages
        self.jinja = Jinja2Renderer()

        # Set the exception class for template errors
        self.template_error = TemplateError

        # Set the custom exception class for handling errors
        self.exceptions = exceptions

        # Set the utility function for getting emoji by name
        self.emojis = EmojiConverter()

        # Set the utility function for rounding up tuple values
        self.round_up_tuple = round_up_tuple

        # Initialize the adapter object for interacting with the psutil library
        self.psutil_adapter = PsutilAdapter()
