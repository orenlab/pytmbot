#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from typing import Any

from app.core.handlers.handler import Handler
from app import build_logger
from app.core.adapters.psutil_adapter import PsutilAdapter


class MemoryHandler(Handler):
    """Class for handling memory usage"""

    def __init__(self, bot):
        """Initialize memory handler"""
        super().__init__(bot)
        self.log = build_logger(__name__)
        self.psutil_adapter = PsutilAdapter()

    def get_data(self) -> tuple:
        """Use psutil to gather data off memory used"""
        data = self.psutil_adapter.get_memory()
        return data

    def compile_message(self) -> dict[str, Any]:
        """Use psutil to gather data on the memory load"""
        try:
            value = self.get_data()
            context = {
                'total': self.format_bytes(getattr(value, 'total')),
                'available': self.format_bytes(getattr(value, 'available')),
                'percent': getattr(value, 'percent'),
                'used': self.format_bytes(getattr(value, 'used')),
                'free': self.format_bytes(getattr(value, 'free')),
                'active': self.format_bytes(getattr(value, 'active')),
                'inactive': self.format_bytes(getattr(value, 'inactive')),
                'cached': self.format_bytes(getattr(value, 'cached')),
                'shared': self.format_bytes(getattr(value, 'shared')),
            }
            return context
        except ValueError as err:
            raise self.exceptions.PyTeleMonBotHandlerError(
                self.bot_msg_tpl.VALUE_ERR_TEMPLATE
            ) from err

    def get_answer(self) -> str:
        """Parsing answer to template"""
        try:
            tpl = self.jinja.get_template('memory.jinja2')
            context = self.compile_message()
            bot_answer = tpl.render(
                thought_balloon=self.get_emoji('thought_balloon'),
                abacus=self.get_emoji('abacus'),
                context=context
            )
            return bot_answer
        except self.TemplateError as err_tpl:
            raise self.exceptions.PyTeleMonBotTemplateError(
                self.bot_msg_tpl.TPL_ERR_TEMPLATE
            ) from err_tpl

    def handle(self):
        """Abstract method"""

        @self.bot.message_handler(regexp="Memory load")
        def get_memory(message) -> None:
            """Main handler for the Memory info"""
            try:
                self.log.info(self.bot_msg_tpl.HANDLER_START_TEMPLATE.format(
                    "Memory handler",
                    message.from_user.username,
                    message.from_user.id,
                    message.from_user.language_code,
                    message.from_user.is_bot
                ))
                inline_button = self.keyboard.build_inline_keyboard("Swap info", "swap_info")
                self.bot.send_message(message.chat.id, text=self.get_answer(), reply_markup=inline_button)
            except ConnectionError as err:
                raise self.exceptions.PyTeleMonBotConnectionError(
                    self.bot_msg_tpl.VALUE_ERR_TEMPLATE
                ) from err
