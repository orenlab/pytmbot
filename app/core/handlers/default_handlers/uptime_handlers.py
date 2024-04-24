#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from app.core.handlers.handler import Handler
from app import bot_logger
from telebot.types import Message


class UptimeHandler(Handler):
    def __init__(self, bot):
        super().__init__(bot)

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
        def get_uptime(message: Message) -> None:
            """Get uptime info"""
            try:
                self.bot.send_chat_action(message.chat.id, 'typing')
                bot_logger.info(self.bot_msg_tpl.HANDLER_START_TEMPLATE.format(
                    message.from_user.username,
                    message.from_user.id,
                    message.from_user.language_code,
                    message.from_user.is_bot))
                uptime_bot_answer = self._compile_message()
                self.bot.send_message(
                    message.chat.id,
                    text=uptime_bot_answer
                )
            except ConnectionError:
                raise self.exceptions.PyTeleMonBotHandlerError(
                    self.bot_msg_tpl.VALUE_ERR_TEMPLATE
                )
