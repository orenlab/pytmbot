#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from app.core.handlers.handler import Handler
from app import build_logger
from app.core.adapters.psutil_adapter import PsutilAdapter


class LoadAvgHandler(Handler):
    """Class to handle loading the average"""

    def __init__(self, bot) -> None:
        """Initialize the LoadAvgHandler"""
        super().__init__(bot)
        self.log = build_logger(__name__)
        self.psutil_adapter = PsutilAdapter()

    def get_data(self) -> tuple:
        """Use psutil to gather data on the processor load"""
        data = self.psutil_adapter.get_load_average()
        return data

    def compile_message(self) -> str:
        """Compile the message to send to the bot"""
        try:
            tpl = self.jinja.get_template('load_average.jinja2')
            bot_answer: str | None = tpl.render(
                thought_balloon=self.get_emoji('thought_balloon'),
                desktop_computer=self.get_emoji('desktop_computer'),
                context=self.round_up_tuple(self.get_data()))
            return bot_answer
        except self.TemplateError as err_tpl:
            raise self.exceptions.PyTeleMonBotTemplateError(
                self.bot_msg_tpl.TPL_ERR_TEMPLATE
            ) from err_tpl

    def handle(self):
        """Abstract method"""

        @self.bot.message_handler(regexp="Load average")
        def get_average(message) -> None:
            """Main load average handler"""
            try:
                bot_answer: str = self.compile_message()
                inline_button = self.keyboard.build_inline_keyboard(
                    "History",
                    "history_load"
                )
                self.bot.send_message(
                    message.chat.id,
                    text=bot_answer,
                    reply_markup=inline_button
                )
            except ValueError as err:
                raise self.exceptions.PyTeleMonBotHandlerError(
                    self.bot_msg_tpl.VALUE_ERR_TEMPLATE
                ) from err
