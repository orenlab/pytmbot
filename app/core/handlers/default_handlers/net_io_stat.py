#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from telebot.types import Message

from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_handler_session


class NetIOHandler(HandlerConstructor):
    """Class to handle loading the average"""

    def _get_data(self):
        """Use psutil to gather data on the network cards io stats"""
        data = self.psutil_adapter.get_net_io_counters()
        return data

    def _compile_message(self) -> str:
        """Compile the message to send to the bot"""
        try:
            bot_answer: str | None = self.jinja.render_templates(
                'net_io.jinja2',
                thought_balloon=self.get_emoji('thought_balloon'),
                up_left_arrow=self.get_emoji('up-left_arrow'),
                up_right_arrow=self.get_emoji('up-right_arrow'),
                globe_showing_europe_africa=self.get_emoji('globe_showing_Europe-Africa'),
                hugging_face=self.get_emoji('smiling_face_with_open_hands'),
                context=self._get_data()
            )
            return bot_answer
        except ValueError:
            self.exceptions.PyTeleMonBotHandlerError("Error parsing data")

    def handle(self):
        """
        Methods to handle network io data
        """

        @self.bot.message_handler(regexp="Network")
        @logged_handler_session
        def get_average(message: Message) -> None:
            """Main load average handler"""
            try:
                self.bot.send_chat_action(message.chat.id, 'typing')
                bot_answer: str = self._compile_message()
                HandlerConstructor._send_bot_answer(
                    self,
                    message.chat.id,
                    text=bot_answer
                )
            except ValueError:
                raise self.exceptions.PyTeleMonBotHandlerError(
                    self.bot_msg_tpl.VALUE_ERR_TEMPLATE
                )
