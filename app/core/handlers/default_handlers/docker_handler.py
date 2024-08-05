#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from typing import Any, Optional, Dict

from telebot.types import Message

from app.core.adapters.docker_adapter import DockerAdapter
from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_handler_session, bot_logger


class DockerHandler(HandlerConstructor):
    """
    Handler for docker related commands
    """

    @staticmethod
    def __fetch_counters() -> Optional[Dict[str, int]]:
        """
        Fetch Docker counters.

        Returns:
            Optional[Dict[str, int]]: A dictionary containing Docker counters, or None if the counters cannot be
            fetched.
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
        @self.bot.message_handler(commands=["docker"])
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

            except (AttributeError, ValueError) as err:
                # Raise an exception if there is a ValueError while rendering the templates
                raise self.exceptions.PyTeleMonBotHandlerError(f"Failed at @{__name__}: {str(err)}")
