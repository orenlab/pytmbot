#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from telebot.types import Message

from app import logged_handler_session
from app.core.handlers.handler import Handler


class LoadAvgHandler(Handler):
    """Class to handle loading the average"""

    def __init__(self, bot) -> None:
        """Initialize the LoadAvgHandler"""
        super().__init__(bot)

    def _get_data(self) -> tuple:
        """Use psutil to gather data on the processor load"""
        data = self.psutil_adapter.get_load_average()
        return data

    def _compile_message(self) -> str:
        """Compile the message to send to the bot"""
        try:
            bot_answer: str | None = self.jinja.render_templates(
                'load_average.jinja2',
                thought_balloon=self.get_emoji('thought_balloon'),
                desktop_computer=self.get_emoji('desktop_computer'),
                context=self.round_up_tuple(self._get_data()))
            return bot_answer
        except ValueError:
            self.exceptions.PyTeleMonBotHandlerError("Error parsing data")

    def handle(self):
        """Abstract method"""

        @self.bot.message_handler(regexp="Load average")
        @logged_handler_session
        def get_average(message: Message) -> None:
            """Main load average handler"""
            try:
                self.bot.send_chat_action(message.chat.id, 'typing')
                bot_answer: str = self._compile_message()
                Handler._send_bot_answer(self, message, bot_answer)
            except ValueError:
                raise self.exceptions.PyTeleMonBotHandlerError(
                    self.bot_msg_tpl.VALUE_ERR_TEMPLATE
                )
