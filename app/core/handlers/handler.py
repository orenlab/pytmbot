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
    """
    Base class for handlers.

    This class initializes the handler with necessary attributes and dependencies.

    Attributes:
        bot (telebot.TeleBot): The Telegram bot instance.
        keyboard (Keyboard): The keyboard object for building reply and inline keyboards.
        bot_msg_tpl (MessageTpl): The message template object for formatting bot messages.
        config (Config): The configuration object containing bot settings.
        jinja (Jinja2Renderer): The Jinja2 renderer object for templating bot messages.
        TemplateError (TemplateError): The exception class for template errors.
        exceptions (Exceptions): The custom exception class for handling Telegram API errors.
        get_emoji (function): The utility function for getting emoji by name.
        round_up_tuple (function): The utility function for rounding up tuple values.
        psutil_adapter (PsutilAdapter): The adapter object for interacting with the psutil library.
    """

    def __init__(self, bot):
        """
        Initialize the handler class.

        Args:
            bot (telebot.TeleBot): The Telegram bot instance.
        """
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
        """
        Send the bot answer.

        Args:
            *args: Positional arguments to be passed to bot.send_message().
            **kwargs: Keyword arguments to be passed to bot.send_message().

        Raises:
            ConnectionError: If there is a connection error while sending the message.
            ApiTelegramException: If there is an API Telegram exception while sending the message.

        Returns:
            None
        """
        try:
            # Send the message using the bot object
            self.bot.send_message(*args, **kwargs)
        except (ConnectionError, ApiTelegramException) as e:
            # Log the error if there is an exception
            bot_logger.error(f"Failed at @{__name__}: {e}")
