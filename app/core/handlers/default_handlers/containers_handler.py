#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from functools import lru_cache
from typing import Union, Dict, List

from docker.errors import DockerException
from telebot.types import Message

from app.core.adapters.docker_adapter import DockerAdapter
from app.core.handlers.handler import HandlerConstructor
from app.core.logs import bot_logger
from app.core.logs import logged_handler_session


class ContainersHandler(HandlerConstructor):

    @staticmethod
    def __get_container_data() -> Union[list[Dict[str, str]], Dict[None, None]]:
        """
        Gets container data from the DockerAdapter.

        Returns:
            Union[list[Dict[str, str]], Dict[None, None]]: A list of container data or an empty dictionary.

        Raises:
            DockerException: If a DockerException occurs during the retrieval process.
        """
        try:
            # Create an instance of DockerAdapter and retrieve image details in one line
            return DockerAdapter().retrieve_containers_stats()
        except DockerException as e:
            # Log an error message if a DockerException occurs
            error_msg = f'Failed at {__name__}: {e}'
            bot_logger.error(error_msg)
            return {}

    def __compile_message(self) -> tuple[str, list[str] | None]:
        """
        Compiles the message to be sent to the bot based on the container data.

        Returns:
            tuple[str, list[str] | None]: The compiled message to be sent to the bot and a list of container names
                if available, or None if no container data is available.

        Raises:
            PyTeleMonBotHandlerError: If there is an error parsing the data.
        """
        try:
            # Get container data
            container_data: dict = self.__get_container_data()

            if not container_data:
                # Use 'none.jinja2' template if no container data
                template_name: str = 'none.jinja2'

                # Define context and emojis
                context: str = "There are no containers or incorrect settings are specified."
                emojis: dict = {
                    'thought_balloon': self.emojis.get_emoji('thought_balloon'),
                }

                containers_name = None
            else:
                # Use 'containers.jinja2' template if there is container data
                template_name: str = 'containers.jinja2'

                # Use container_data as the context
                context: dict = container_data

                containers_name = [container.get('name') for container in context]

                # Define emojis for rendering
                emojis: dict = {
                    'thought_balloon': self.emojis.get_emoji('thought_balloon'),
                    'luggage': self.emojis.get_emoji('pushpin'),
                    'minus': self.emojis.get_emoji('minus'),
                }

            # Render the template with the context data and emojis
            return self.jinja.render_templates(template_name, **emojis, context=context), containers_name

        except ValueError:
            # Raise an error if there is an issue parsing the data
            raise self.exceptions.PyTeleMonBotHandlerError("Error parsing data")

    @lru_cache
    def get_list_of_containers_again(self) -> tuple[str, List[str] | None]:
        """
        Get the list of containers again.

        Args:
            self: The ContainersHandler instance.

        Returns:
            tuple[str, List[str] | None]: The compiled message to be sent to the bot and a list of container names
                if available, or None if no container data is available.
        """
        return self.__compile_message()

    def handle(self):
        """
        This function sets up a message handler for the 'Containers' regex pattern.
        It logs the handler session, sends a typing action, and sends a message
        with the docker containers info or an error message.
        """

        @self.bot.message_handler(regexp="Containers")
        @self.bot.message_handler(commands=["containers"])
        @logged_handler_session
        def handle_containers(message: Message) -> None:
            """
            Handles the 'Containers' message by compiling and sending the message to the user or sending an error
            message.

            Args:
                message (telegram.Message): The message object.

            Returns:
                None
            """
            try:
                # Send a typing action to indicate processing
                __send_typing_action(message)

                # Compile the message to be sent to the user
                containers_info = self.__compile_message()

                # Build an inline keyboard for the message
                inline_keyboard = self.keyboard.build_inline_keyboard(*containers_info[1],
                                                                      callback_data_prefix='__get_full__')

                # Send the message to the user
                __send_message(message, containers_info[0], inline_keyboard)

            except ValueError as error:
                # Log the error and send an error message to the user
                __log_error(error)
                __send_error_message(message)

        def __send_typing_action(message):
            """
            Sends a typing action to indicate processing.

            Args:
                message (telegram.Message): The message object.

            Returns:
                None
            """
            self.bot.send_chat_action(message.chat.id, 'typing')

        def __send_message(message, text, reply_markup=None):
            """
            Sends a message to the user.

            Args:
                message (telebot.Message): The message object.
                text (str): The text of the message.
                reply_markup (telegram.ReplyKeyboardMarkup, optional): The inline keyboard. Defaults to None.

            Returns:
                None
            """
            self.bot.send_message(
                message.chat.id,
                text=text,
                reply_markup=reply_markup,
                parse_mode="HTML"
            )

        def __log_error(error):
            """
            Logs the error.

            Args:
                error (Exception): The error to be logged.

            Returns:
                None
            """
            bot_logger.error(error)

        def __send_error_message(message):
            """
            Sends an error message to the user.

            Args:
                message (telegram.Message): The message object.

            Returns:
                None
            """
            error_message = "An error occurred. Please try again later."
            self.bot.send_message(message.chat.id, text=error_message)
