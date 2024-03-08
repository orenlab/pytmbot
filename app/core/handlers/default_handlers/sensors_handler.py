#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from app.core.handlers.handler import Handler
from app import build_logger
from app.core.adapters.psutil_adapter import PsutilAdapter


class SensorsHandler(Handler):
    def __init__(self, bot):
        super().__init__(bot)
        self.log = build_logger(__name__)
        self.psutil_adapter = PsutilAdapter()

    def handle(self):
        @self.bot.message_handler(regexp="Sensors")
        def get_sensors(message) -> None:
            """
            Get all sensors information
            """
            try:
                self.log.info(self.bot_msg_tpl.HANDLER_START_TEMPLATE.format(
                    message.from_user.username,
                    message.from_user.id,
                    message.from_user.language_code,
                    message.from_user.is_bot
                ))
                context = self.api_data.get_metrics('sensors')
                context_sensors = {}
                for data in context:
                    context_sensors.update({data['label']: data['value']})
                bot_answer = self.jinja.render_templates(
                    'sensors.jinja2',
                    thought_balloon=self.get_emoji('thought_balloon'),
                    thermometer=self.get_emoji('thermometer'),
                    exclamation=self.get_emoji('red_exclamation_mark'),
                    melting_face=self.get_emoji('melting_face'),
                    context=context_sensors)
                self.bot.send_message(message.chat.id, text=bot_answer)
            except ValueError as err:
                raise self.exceptions.PyTeleMonBotHandlerError(
                    self.bot_msg_tpl.VALUE_ERR_TEMPLATE
                ) from err

            except self.TemplateError as err_tpl:
                raise self.exceptions.PyTeleMonBotTemplateError(
                    self.bot_msg_tpl.TPL_ERR_TEMPLATE
                ) from err_tpl
