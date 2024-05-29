#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from telebot.types import Message

from app import logged_handler_session
from app.core.handlers.handler import Handler


class ProcessHandler(Handler):
    def __init__(self, bot):
        super().__init__(bot)

    def _get_data(self) -> tuple:
        """Use psutil to gather data off memory used"""
        data = self.psutil_adapter.get_process_counts()
        return data

    def _compile_message(self) -> tuple:
        """Use psutil to gather data on the memory load"""
        try:
            context = self._get_data()
            return context
        except ValueError:
            raise self.exceptions.PyTeleMonBotHandlerError(
                self.bot_msg_tpl.VALUE_ERR_TEMPLATE
            )

    def _get_answer(self) -> str:
        """Parsing answer to template"""
        try:
            context = self._compile_message()
            bot_answer = self.jinja.render_templates(
                'process.jinja2',
                thought_balloon=self.get_emoji('thought_balloon'),
                horizontal_traffic_light=self.get_emoji('horizontal_traffic_light'),
                context=context
            )
            return bot_answer
        except self.TemplateError:
            raise self.exceptions.PyTeleMonBotTemplateError(
                self.bot_msg_tpl.TPL_ERR_TEMPLATE
            )

    def handle(self):
        @self.bot.message_handler(regexp="Process")
        @logged_handler_session
        def get_process(message: Message) -> None:
            """Get process count"""
            try:
                self.bot.send_chat_action(message.chat.id, 'typing')
                self.bot.send_message(message.chat.id, text=self._get_answer())
            except ConnectionError:
                raise self.exceptions.PyTeleMonBotHandlerError(
                    self.bot_msg_tpl.VALUE_ERR_TEMPLATE
                )
