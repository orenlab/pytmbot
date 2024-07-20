#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from typing import Any, Optional

from telebot.types import Message

from app.core.adapters.docker_adapter import DockerAdapter
from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_handler_session, bot_logger


class DockerHandler(HandlerConstructor):
    """
    Handler for docker related commands
    """

    @staticmethod
    def __fetch_counters():
        """
        Fetch docker data.

        Returns:
            Optional[list]: A list of Docker images if found, None if no images are found or an error occurs.
        """
        return DockerAdapter().fetch_docker_counters()

    def __compile_message(self) -> dict[str, str] | str | Any:
        """
        Compile message and render a bot answer based on docker counters.

        Args:
            self: The DockerHandler object.

        Returns:
            dict[str, str] | str | Any: The compiled bot answer based on docker counters or N/A if no counters
            are found.
        """
        docker_counters = self.__fetch_counters()
        if docker_counters is None:
            return {"images_count": "N/A", "containers_count": "N/A"}

        emojis = {
            'thought_balloon': self.emojis.get_emoji('thought_balloon'),
            'spouting_whale': self.emojis.get_emoji('spouting_whale'),
            'backhand_index_pointing_down': self.emojis.get_emoji('backhand_index_pointing_down'),
        }

        try:
            bot_answer = self.jinja.render_templates('docker.jinja2', context=docker_counters, **emojis)
            return bot_answer
        except Exception as error:
            bot_logger.error(f"Failed at @{__name__}: {error}")
            return {"images_count": "N/A", "containers_count": "N/A"}

    def handle(self) -> None:
        """
        Methods to handle containers data
        """

        @self.bot.message_handler(regexp="Docker")
        @logged_handler_session
        def docker_handler(message: Message) -> None:
            try:
                # Send a typing action to indicate that the bot is processing the message
                self.bot.send_chat_action(message.chat.id, 'typing')

                # Compile the message to send to the bot
                bot_answer: str = self.__compile_message()

                reply_keyboard = self.keyboard.build_reply_keyboard(keyboard_type='docker_keyboard')

                # Send the compiled message to the bot
                self.bot.send_message(
                    message.chat.id,
                    text=bot_answer,
                    reply_markup=reply_keyboard,
                    parse_mode='HTML'
                )
            except ValueError:
                # Raise an exception if there is an error parsing the data
                raise self.exceptions.PyTeleMonBotHandlerError(
                    self.bot_msg_tpl.VALUE_ERR_TEMPLATE
                )
