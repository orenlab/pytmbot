#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from telebot.types import Message

from app import bot_logger
from app.core.handlers.handler import Handler
from app.core.logs import logged_handler_session


class SensorsHandler(Handler):
    def __init__(self, bot):
        """Initialize the SensorsHandler"""
        super().__init__(bot)
        self.log = bot_logger

    def _get_data(self):
        """Use psutil to gather data on the local filesystem"""
        data = self.psutil_adapter.get_sensors_temperatures()
        return data

    def _compile_message(self) -> str:
        """Compile the message to be sent to the bot"""
        try:
            context = self._get_data()
            if not context:
                self.log.error("Cannot get sensors data")
                bot_answer = "Sorry, I couldn't find any sensors. Something went wrong :("
            else:
                bot_answer = self.jinja.render_templates(
                    'sensors.jinja2',
                    thought_balloon=self.get_emoji('thought_balloon'),
                    thermometer=self.get_emoji('thermometer'),
                    exclamation=self.get_emoji('red_exclamation_mark'),
                    melting_face=self.get_emoji('melting_face'),
                    context=context
                )
            return bot_answer
        except ValueError:
            self.log.exception("Error while compiling message")

    def handle(self):
        @self.bot.message_handler(regexp="Sensors")
        @logged_handler_session
        def get_sensors(message: Message) -> None:
            """Get all sensors information"""
            try:
                self.bot.send_chat_action(message.chat.id, 'typing')
                sensors_bot_answer = self._compile_message()
                Handler._send_bot_answer(
                    self,
                    message.chat.id,
                    text=sensors_bot_answer,
                )
            except (ConnectionError, ValueError):
                self.log.exception("Error while handling message")
