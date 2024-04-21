#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
import docker

from app.core.handlers.handler import Handler
from app import bot_logger
from telebot.types import Message

from app.core.adapters.docker_adapter import DockerAdapter
from docker.errors import DockerException


class ContainersHandler(Handler):
    def __init__(self, bot):
        """Initialize the ContainersHandler"""
        super().__init__(bot)
        self.log = bot_logger
        self.docker_adapter = DockerAdapter()

    def _get_data(self):
        """Use docker adapter to gather containers information"""
        try:
            data = self.docker_adapter.check_image_details()
            return data
        except DockerException:
            bot_logger.error('Error connecting to the Docker socket')
            return {}

    def _compile_message(self) -> str:
        """Compile the message to be sent to the bot"""
        try:
            context = self._get_data()
            if context == {} or not context:
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
                self.bot.send_chat_action(message.chat.id, 'typing')
                bot_logger.info(self.bot_msg_tpl.HANDLER_START_TEMPLATE.format(
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
            except ValueError:
                self.log.error("Error while handling message")
                self.bot.send_message(
                    message.chat.id,
                    text="Error occurred while getting containers info :("
                )
