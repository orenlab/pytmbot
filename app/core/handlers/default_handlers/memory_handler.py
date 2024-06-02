#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from telebot.types import Message

from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_handler_session


class MemoryHandler(HandlerConstructor):
    """Class for handling memory usage"""

    def _get_data(self) -> tuple:
        """Use psutil to gather data off memory used"""
        data = self.psutil_adapter.get_memory()
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
                'memory.jinja2',
                thought_balloon=self.get_emoji('thought_balloon'),
                abacus=self.get_emoji('abacus'),
                context=context
            )
            return bot_answer
        except self.TemplateError:
            raise self.exceptions.PyTeleMonBotTemplateError(
                self.bot_msg_tpl.TPL_ERR_TEMPLATE
            )

    def handle(self):
        """Abstract method"""

        @self.bot.message_handler(regexp="Memory load")
        @logged_handler_session
        def get_memory(message: Message) -> None:
            """Main handler for the Memory info"""
            try:
                self.bot.send_chat_action(message.chat.id, 'typing')
                bot_answer = self._get_answer()

                inline_button = self.keyboard.build_inline_keyboard(
                    "Swap info",
                    "swap_info"
                )

                HandlerConstructor._send_bot_answer(
                    self,
                    message.chat.id,
                    text=bot_answer,
                    reply_markup=inline_button
                )
            except ConnectionError:
                raise self.exceptions.PyTeleMonBotConnectionError(
                    self.bot_msg_tpl.VALUE_ERR_TEMPLATE
                )
