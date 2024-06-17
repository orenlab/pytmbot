#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from docker.errors import DockerException
from telebot.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

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
            data = self.docker_adapter.retrieve_image_details()
            return data
        except DockerException:
            # Log an error if there is a DockerException
            bot_logger.error(f'Failed at {__name__}: Error connecting to the Docker socket')
            return {}

    def _compile_message(self) -> tuple[str, list[str] | None]:
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
            container_data: dict = self._get_container_data()

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

    def handle(self):
        """
        This function sets up a message handler for the 'Containers' regex pattern.
        It logs the handler session, sends a typing action, and sends a message
        with the docker containers info or an error message.
        """

        @self.bot.message_handler(regexp="Containers")
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
                send_typing_action(message)
                containers_info = self._compile_message()
                inline_keyboard = build_inline_keyboard(containers_info[1])
                send_message(message, containers_info[0], inline_keyboard)

            except ValueError as error:
                log_error(error)
                send_error_message(message)

        def send_typing_action(message):
            """
            Sends a typing action to indicate processing.
            """
            self.bot.send_chat_action(message.chat.id, 'typing')

        def build_inline_keyboard(container_names: list) -> InlineKeyboardMarkup:
            """
            Constructs an InlineKeyboardMarkup with buttons for each container name.

            Args:
                container_names (list): List of container names.

            Returns:
                InlineKeyboardMarkup: Inline keyboard with buttons.
            """
            return InlineKeyboardMarkup(
                [[
                    InlineKeyboardButton(text=container_name, callback_data=f"get_full[{container_name}]")
                    for container_name in container_names
                ]]
            )

        def send_message(message, text, reply_markup=None):
            """
            Sends a message to the user.

            Args:
                message (telegram.Message): The message object.
                text (str): The text of the message.
                reply_markup (telegram.ReplyKeyboardMarkup, optional): The inline keyboard. Defaults to None.
            """
            self.bot.send_message(
                message.chat.id,
                text=text,
                reply_markup=reply_markup
            )

        def log_error(error):
            """
            Logs the error.

            Args:
                error (Exception): The error object.
            """
            bot_logger.error(f"Failed at {__name__}: {str(error)}")

        def send_error_message(message):
            """
            Sends an error message to the user.

            Args:
                message (telegram.Message): The message object.
            """
            self.bot.send_message(
                message.chat.id,
                text="Error occurred while getting containers info :("
            )
