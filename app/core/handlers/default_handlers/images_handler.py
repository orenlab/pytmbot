#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from telebot.types import Message

from app.core.adapters.docker_adapter import DockerAdapter
from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_handler_session, bot_logger


class ImagesHandler(HandlerConstructor):
    """
    A class for handling images-related commands.
    """
    @staticmethod
    def __fetch_data():
        """
        Fetches the data from the Docker Adapter.

        This method creates an instance of the DockerAdapter class and calls its
        fetch_image_details() method to retrieve the image details.

        Returns:
            Dict[str, Dict[str, object]]: A dictionary containing image details.
        """
        # Create an instance of the DockerAdapter class
        adapter = DockerAdapter()

        # Call the fetch_image_details() method of the DockerAdapter instance
        # to retrieve the image details
        return adapter.fetch_image_details()

    def __compile_message(self):
        """
        Compiles the message to be sent to the bot.

        Fetches data from the Docker Adapter and compiles the message template based on the retrieved data.

        Returns:
            str: The compiled message to be sent to the bot.
        """
        # Fetch data from the Docker Adapter
        docker_images = self.__fetch_data()

        if docker_images is None:
            # If no docker images are found, set default values
            template_name = 'none.jinja2'
            docker_images = "There are no images or incorrect settings are specified."
            emojis = {'thought_balloon': self.emojis.get_emoji('thought_balloon')}
        else:
            # If docker images are found, set the proper template and emojis
            template_name = 'images.jinja2'
            emojis = {
                'thought_balloon': self.emojis.get_emoji('thought_balloon'),
                'spouting_whale': self.emojis.get_emoji('spouting_whale'),
                'minus': self.emojis.get_emoji('minus'),
            }

        try:
            # Render the message template with the data and emojis
            return self.jinja.render_templates(template_name, context=docker_images, **emojis)
        except Exception as error:
            # Log error if rendering fails
            bot_logger.error(f"Failed at @{__name__}: {error}")

    def handle(self):
        """
        Handles the Docker images data.
        """

        @self.bot.message_handler(regexp="Images")
        @logged_handler_session
        def docker_images(message: Message) -> None:
            """
            Handler for the 'Images' message.

            This function is triggered when the user sends a message that matches the regexp "Images".
            It sends a typing action to the user, builds a main keyboard, gets the user's first name, renders a
            template,and sends the rendered template to the user with the main keyboard.

            Args:
                message (telebot.types.Message): The message object received from the user.

            Returns:
                None

            Raises:
                PyTeleMonBotHandlerError: If there is a ValueError while rendering the templates.
            """
            try:
                # Send typing action to the user
                self.bot.send_chat_action(message.chat.id, 'typing')

                # Build the main keyboard
                reply_keyboard = self.keyboard.build_reply_keyboard(keyboard_type='docker_keyboard')

                # Send the bot answer to the user with the main keyboard
                self.bot.send_message(
                    message.chat.id,
                    text=self.__compile_message(),
                    reply_markup=reply_keyboard,
                    parse_mode="HTML"
                )
            except ValueError:
                # Raise an exception if there is a ValueError while rendering the templates
                raise self.exceptions.PyTeleMonBotHandlerError(
                    self.bot_msg_tpl.VALUE_ERR_TEMPLATE
                )
