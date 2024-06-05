#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from docker.errors import DockerException
from telebot.types import Message

from app.core.adapters.docker_adapter import DockerAdapter
from app.core.handlers.handler import HandlerConstructor
from app.core.logs import bot_logger
from app.core.logs import logged_handler_session


class ContainersHandler(HandlerConstructor):
    def __init__(self, bot):
        """
        Initialize the ContainersHandler.

        Args:
            bot (telebot.TeleBot): The Telegram bot instance.
        """
        # Call the parent class initializer
        super().__init__(bot)

        # Initialize the DockerAdapter instance
        self.docker_adapter = DockerAdapter()

    def _get_data(self):
        """
        Use the DockerAdapter to gather information about containers.

        Returns:
            dict: The container information if successful, an empty dictionary otherwise.
        """
        try:
            # Use the DockerAdapter to check the image details
            data = self.docker_adapter.check_image_details()
            return data
        except DockerException:
            # Log an error if there is a DockerException
            bot_logger.error(f'Failed at {__name__}: Error connecting to the Docker socket')
            return {}

    def _compile_message(self) -> str:
        """
        Compile the message to be sent to the bot.

        Retrieves data using the _get_data method and generates a message based on the data.
        If the data is empty or None, renders a template with a message indicating that there are no containers or
        incorrect settings. Otherwise, renders a template with the container information.

        Returns:
            str: The compiled message to be sent to the bot.

        Raises:
            PyTeleMonBotHandlerError: If there is an error parsing the data.
        """
        try:
            data = self._get_data()

            if not data:
                template_name = 'none.jinja2'
                template_context = {
                    'thought_balloon': self.get_emoji('thought_balloon'),
                    'context': "There are no containers or incorrect settings are specified...."
                }
            else:
                template_name = 'containers.jinja2'
                template_context = {
                    'thought_balloon': self.get_emoji('thought_balloon'),
                    'luggage': self.get_emoji('pushpin'),
                    'minus': self.get_emoji('minus'),
                    'context': data
                }

            bot_answer = self.jinja.render_templates(template_name, **template_context)
            return bot_answer
        except ValueError:
            # Raise an exception if there is an error parsing the data
            self.exceptions.PyTeleMonBotHandlerError("Error parsing data")

    def handle(self):
        """
        This function sets up a message handler for the 'Containers' regex pattern.
        It logs the handler session, sends a typing action, and sends a message
        with the docker containers info or an error message.
        """

        @self.bot.message_handler(regexp="Containers")
        @logged_handler_session
        def get_containers(message: Message) -> None:
            """
            Handles the 'Containers' message.
            Compiles the message and sends it to the user or sends an error message.

            Args:
                message (telegram.Message): The message object.

            Returns:
                None
            """
            try:
                # Send typing action to indicate processing
                self.bot.send_chat_action(message.chat.id, 'typing')

                # Compile the message
                containers_bot_answer = self._compile_message()

                # Send the message to the user
                HandlerConstructor._send_bot_answer(
                    self,
                    message.chat.id,
                    text=containers_bot_answer
                )
            except ValueError:
                # Log the error
                bot_logger.error(f"Failed at {__name__}: Error while handling message")

                # Send an error message to the user
                self.bot.send_message(
                    message.chat.id,
                    text="Error occurred while getting containers info :("
                )
