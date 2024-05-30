#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from telebot.types import Message

from app.core.handlers.handler import Handler
from app.core.logs import logged_handler_session


class FileSystemHandler(Handler):
    def __init__(self, bot):
        super().__init__(bot)

    def _get_data(self):
        """Use psutil to gather data on the local filesystem"""
        data = self.psutil_adapter.get_disk_usage()
        return data

    def _compile_message(self) -> str:
        """Compile the message to be sent to the bot"""
        try:
            context = self._get_data()
            bot_answer = self.jinja.render_templates(
                'fs.jinja2',
                thought_balloon=self.get_emoji('thought_balloon'),
                floppy_disk=self.get_emoji('floppy_disk'),
                minus=self.get_emoji('minus'),
                context=context
            )
            return bot_answer
        except ValueError:
            self.exceptions.PyTeleMonBotHandlerError("Error parsing data")

    def handle(self):
        @self.bot.message_handler(regexp="File system")
        @logged_handler_session
        def get_fs(message: Message) -> None:
            """Get file system info"""
            try:
                self.bot.send_chat_action(message.chat.id, 'typing')
                bot_answer: str = self._compile_message()
                Handler._send_bot_answer(
                    self,
                    message.chat.id,
                    text=bot_answer
                )
            except ConnectionError:
                raise self.exceptions.PyTeleMonBotHandlerError(
                    self.bot_msg_tpl.VALUE_ERR_TEMPLATE
                )
