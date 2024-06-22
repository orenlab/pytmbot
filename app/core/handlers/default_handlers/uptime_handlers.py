#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from telebot.types import Message

from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_handler_session


class UptimeHandler(HandlerConstructor):

    def _get_data(self) -> dict:
        """
        Use psutil to gather data on the local filesystem.

        Returns:
            dict: A dictionary containing the uptime information.
        """
        # Use the psutil_adapter to get the uptime data
        data: dict = self.psutil_adapter.get_uptime()

        return data

    def _compile_message(self) -> str:
        """
        Compile the message to be sent to the bot with context data and emojis.

        Args:
            self: Instance of the UptimeHandler class.

        Returns:
            str: The compiled message to be sent to the bot.

        Raises:
            PyTeleMonBotHandlerError: If there is an error parsing the data.
        """

        try:
            # Retrieve data using the `_get_data` method
            context: dict = self._get_data()

            # Define the Jinja template to be used
            template_name: str = 'uptime.jinja2'

            # Prepare the context variables for the Jinja template
            emojis: dict = {
                'thought_balloon': self.emojis.get_emoji('thought_balloon'),  # Emoji for 'thought balloon'
                'hourglass_not_done': self.emojis.get_emoji('hourglass_not_done'),  # Emoji for 'hourglass not done'
            }

            # Render the Jinja template with the context variables
            bot_answer: str = self.jinja.render_templates(template_name, context=context, **emojis)
            return bot_answer
        except ValueError:
            # Raise a custom exception if there is an error parsing the data
            raise self.exceptions.PyTeleMonBotHandlerError("Error parsing data")

    def handle(self):
        """
        Handle the 'Uptime' message by sending the uptime information to the bot.
        """

        # Define a message handler for the 'Uptime' message
        @self.bot.message_handler(regexp="Uptime")
        @logged_handler_session
        def get_uptime(message: Message) -> None:
            """
            Get uptime info and send it to the bot.

            Args:
                message (telebot.types.Message): The message received from the user.
            """
            try:
                # Send a 'typing' action to the user to indicate that the bot is processing the request
                self.bot.send_chat_action(message.chat.id, 'typing')

                # Compile the uptime message using the '_compile_message' method
                uptime_bot_answer = self._compile_message()

                # Send the compiled message to the bot using the '_send_bot_answer' method
                HandlerConstructor._send_bot_answer(
                    self,
                    message.chat.id,
                    text=uptime_bot_answer,
                )
            except ConnectionError:
                # Raise an exception if there is a connection error while sending the message
                raise self.exceptions.PyTeleMonBotHandlerError(
                    self.bot_msg_tpl.VALUE_ERR_TEMPLATE
                )
