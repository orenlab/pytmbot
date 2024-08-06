#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from typing import Dict

from app.core.adapters.docker_adapter import DockerAdapter
from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_handler_session, bot_logger


class ImagesHandler(HandlerConstructor):
    """
    A class for handling images-related commands.
    """

    @staticmethod
    def __fetch_data() -> Dict[str, Dict[str, object]]:
        """
        Fetches the data from the Docker Adapter.

        Returns:
            Dict[str, Dict[str, object]]: A dictionary containing image details.
        """
        return DockerAdapter().fetch_image_details()

    def __compile_message(self):
        """
        Compiles the message to be sent to the bot.

        Fetches data from the Docker Adapter and compiles the message template based on the retrieved data.

        Returns:
            str: The compiled message to be sent to the bot.
        """
        # Fetch data from the Docker Adapter
        docker_images = self.__fetch_data()

        # Set the default emojis
        emojis = {'thought_balloon': self.emojis.get_emoji('thought_balloon')}

        # Determine the template name based on whether docker_images is None
        template_name = 'b_none.jinja2' if docker_images is None else 'd_images.jinja2'

        # If docker_images is None, set the default message
        if docker_images is None:
            docker_images = "There are no images or incorrect settings are specified."
        else:
            # If docker_images is not None, update the emojis with additional emojis
            emojis.update({
                'spouting_whale': self.emojis.get_emoji('spouting_whale'),
                'minus': self.emojis.get_emoji('minus'),
            })

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
        @self.bot.message_handler(commands=['images'])
        @logged_handler_session
        def docker_images(message) -> None:
            """
            Handler for the 'Images' message.

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
                reply_keyboard = self.keyboard.build_reply_keyboard(
                    keyboard_type='docker_keyboard')

                # Send the bot answer to the user with the main keyboard
                self.bot.send_message(
                    message.chat.id,
                    text=self.__compile_message(),
                    reply_markup=reply_keyboard,
                    parse_mode="HTML"
                )
            except (AttributeError, ValueError) as err:
                # Raise an exception if there is a ValueError while rendering the templates
                raise self.exceptions.PyTeleMonBotHandlerError(f"Failed at @{__name__}: {str(err)}")
