#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from app.core.handlers.handler import Handler
from app import build_logger
from telebot.types import Message

from app.core.adapters.docker_adapter import DockerAdapter


class ContainersHandler(Handler):
    def __init__(self, bot):
        """Initialize the ContainersHandler"""
        super().__init__(bot)
        self.log = build_logger(__name__)
        self.docker_adapter = DockerAdapter()

    def _get_data(self):
        """Use docker adapter to gather containers information"""
        data = self.docker_adapter.check_image_details()
        return data

    def _compile_message(self) -> str:
        """Compile the message to be sent to the bot"""
        try:
            context = self._get_data()
            if context == {}:
                bot_answer = self.jinja.render_templates(
                    'none.jinja2',
                    thought_balloon=self.get_emoji('thought_balloon')
                )
            else:
                bot_answer = self.jinja.render_templates(
                    'containers.jinja2',
                    thought_balloon=self.get_emoji('thought_balloon'),
                    luggage=self.get_emoji('pushpin'), minus=self.get_emoji('minus'),
                    context=context
                )
            return bot_answer
        except ValueError:
            self.exceptions.PyTeleMonBotHandlerError("Error parsing data")

    def handle(self):
        @self.bot.message_handler(regexp="Containers")
        def get_containers(message: Message) -> None:
            """
            Get docker containers info
            """
            try:
                self.log.info(self.bot_msg_tpl.HANDLER_START_TEMPLATE.format(
                    message.from_user.username,
                    message.from_user.id,
                    message.from_user.language_code,
                    message.from_user.is_bot
                ))
                containers_bot_answer = self._compile_message()
                self.bot.send_message(
                    message.chat.id,
                    text=containers_bot_answer
                )
            except ValueError as err:
                raise self.exceptions.PyTeleMonBotHandlerError(
                    self.bot_msg_tpl.VALUE_ERR_TEMPLATE
                ) from err
