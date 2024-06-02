#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from telebot.types import Message

from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_handler_session


class UptimeHandler(HandlerConstructor):

    def _get_data(self):
        """Use psutil to gather data on the local filesystem"""
        data = self.psutil_adapter.get_uptime()
        return data

    def _compile_message(self) -> str:
        """Compile the message to be sent to the bot"""
        try:
            context = self._get_data()
            bot_answer = self.jinja.render_templates(
                'uptime.jinja2',
                thought_balloon=self.get_emoji('thought_balloon'),
                hourglass_not_done=self.get_emoji('hourglass_not_done'),
                context=context
            )
            return bot_answer
        except ValueError:
            self.exceptions.PyTeleMonBotHandlerError("Error parsing data")

    def handle(self):
        @self.bot.message_handler(regexp="Uptime")
        @logged_handler_session
        def get_uptime(message: Message) -> None:
            """Get uptime info"""
            try:
                self.bot.send_chat_action(message.chat.id, 'typing')
                uptime_bot_answer = self._compile_message()
                HandlerConstructor._send_bot_answer(
                    self,
                    message.chat.id,
                    text=uptime_bot_answer,
                )
            except ConnectionError:
                raise self.exceptions.PyTeleMonBotHandlerError(
                    self.bot_msg_tpl.VALUE_ERR_TEMPLATE
                )
