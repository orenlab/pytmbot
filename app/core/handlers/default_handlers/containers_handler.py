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

    def _get_container_data(self):
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
        Compiles the message to be sent to the bot based on the container data.

        Returns:
            str: The compiled message to be sent to the bot.

        Raises:
            PyTeleMonBotHandlerError: If there is an error parsing the data.
        """
        try:
            # Get container data
            container_data: dict = self._get_container_data()

            # Check if there are no container data
            if not container_data:
                # Use 'none.jinja2' template if no container data
                template_name: str = 'none.jinja2'

                # Define context and emojis
                context: str = "There are no containers or incorrect settings are specified."
                emojis: dict = {
                    'thought_balloon': self.get_emoji('thought_balloon'),
                }
            else:
                # Use 'containers.jinja2' template if there is container data
                template_name: str = 'containers.jinja2'

                # Use container_data as the context
                context: dict = container_data

                # Define emojis for rendering
                emojis: dict = {
                    'thought_balloon': self.get_emoji('thought_balloon'),
                    'luggage': self.get_emoji('pushpin'),
                    'minus': self.get_emoji('minus'),
                }

            # Render the template with the context data and emojis
            return self.jinja.render_templates(template_name, **emojis, context=context)

        except ValueError:
            # Raise an error if there is an issue parsing the data
            raise self.exceptions.PyTeleMonBotHandlerError("Error parsing data")

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
