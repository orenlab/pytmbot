#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from app.core.handlers.handler import Handler
from app import build_logger
from telebot.types import Message


class SensorsHandler(Handler):
    def __init__(self, bot):
        super().__init__(bot)
        self.log = build_logger(__name__)

    def _get_data(self):
        """Use psutil to gather data on the local filesystem"""
        data = self.psutil_adapter.get_sensors_temperatures()
        return data

    def _compile_message(self) -> str:
        """Compile the message to be sent to the bot"""
        try:
            context = self._get_data()

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
            self.exceptions.PyTeleMonBotHandlerError("Error parsing data")

    def handle(self):
        @self.bot.message_handler(regexp="Sensors")
        def get_sensors(message: Message) -> None:
            """Get all sensors information"""
            try:
                self.log.info(self.bot_msg_tpl.HANDLER_START_TEMPLATE.format(
                    message.from_user.username,
                    message.from_user.id,
                    message.from_user.language_code,
                    message.from_user.is_bot
                ))
                sensors_bot_answer = self._compile_message()
                self.bot.send_message(message.chat.id, text=sensors_bot_answer)
            except ConnectionError as err:
                raise self.exceptions.PyTeleMonBotHandlerError(
                    self.bot_msg_tpl.VALUE_ERR_TEMPLATE
                ) from err
