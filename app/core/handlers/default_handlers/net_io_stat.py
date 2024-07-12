#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from telebot.types import Message

from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_handler_session


class NetIOHandler(HandlerConstructor):
    """Class to handle loading the average"""

    def _get_data(self) -> dict:
        """
        Get network card IO statistics using psutil.

        This method utilizes the psutil_adapter to collect network card IO statistics.

        Returns:
            dict: A dictionary containing the network card IO statistics.
        """
        # Utilize psutil to collect network card IO statistics
        data = self.psutil_adapter.get_net_io_counters()

        return data

    def _compile_message(self) -> str:
        """
        Compiles the message using network card IO statistics.

        Retrieves network card IO statistics and generates a message based on the data.
        Utilizes Jinja2 templates to render the message.

        Returns:
            str: The compiled message to be sent to the bot.

        Raises:
            PyTeleMonBotHandlerError: If there is an error parsing the data.
        """
        try:
            # Retrieve network card IO statistics
            context: dict = self._get_data()

            # Define the template name and context variables for network IO statistics
            template_name: str = 'net_io.jinja2'

            emojis: dict = {
                'thought_balloon': self.emojis.get_emoji('thought_balloon'),
                'up_left_arrow': self.emojis.get_emoji('up-left_arrow'),
                'up_right_arrow': self.emojis.get_emoji('up-right_arrow'),
                'globe_showing_europe_africa': self.emojis.get_emoji('globe_showing_Europe-Africa'),
                'hugging_face': self.emojis.get_emoji('smiling_face_with_open_hands'),
            }

            # Render the 'net_io.jinja2' template with the context variables for network IO statistics
            bot_answer: str = self.jinja.render_templates(template_name, **emojis, context=context)
            return bot_answer
        except ValueError:
            # Raise an exception if there is an error parsing the data
            raise self.exceptions.PyTeleMonBotHandlerError("Error parsing data")

    def handle(self):
        """
        Handle network IO data.

        This function sets up a message handler for the "Network" regexp and logs the handler session.
        It then defines the "get_average" function to handle the main load average handler.
        """

        @self.bot.message_handler(regexp="Network")
        @logged_handler_session
        def get_average(message: Message) -> None:
            """
            Main load average handler.

            This function sends a typing action to indicate processing, compiles the message,
            and sends it to the bot.

            Args:
                message (Message): The message object received from the bot.

            Raises:
                PyTeleMonBotHandlerError: If there is an error parsing the data.
            """
            try:
                # Send a typing action to indicate processing
                self.bot.send_chat_action(message.chat.id, 'typing')

                # Compile the message to send to the bot
                bot_answer: str = self._compile_message()

                # Send the compiled message to the bot
                self.bot.send_message(
                    message.chat.id,
                    text=bot_answer
                )
            except ValueError:
                # Raise an exception if there is an error parsing the data
                raise self.exceptions.PyTeleMonBotHandlerError(
                    self.bot_msg_tpl.VALUE_ERR_TEMPLATE
                )
