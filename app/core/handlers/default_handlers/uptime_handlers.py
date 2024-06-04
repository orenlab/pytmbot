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

    def _get_data(self):
        """
        Use psutil to gather data on the local filesystem.

        Returns:
            dict: A dictionary containing the uptime information.
        """
        # Use the psutil_adapter to get the uptime data
        data = self.psutil_adapter.get_uptime()

        return data

    def _compile_message(self) -> str:
        """
        Compile the message to be sent to the bot.

        This method retrieves data using the `_get_data` method and generates a message based on the data.
        It uses Jinja2 templates to render the message.

        Returns:
            str: The compiled message to be sent to the bot.

        Raises:
            PyTeleMonBotHandlerError: If there is an error parsing the data.
        """
        try:
            # Retrieve data using the `_get_data` method
            context = self._get_data()

            # Render a Jinja2 template with the message
            bot_answer = self.jinja.render_templates(
                'uptime.jinja2',  # Template name
                thought_balloon=self.get_emoji('thought_balloon'),  # Emoji for thought balloon
                hourglass_not_done=self.get_emoji('hourglass_not_done'),  # Emoji for hourglass not done
                context=context  # Data to be used in the template
            )
            return bot_answer
        except ValueError:
            # Raise an exception if there is an error parsing the data
            self.exceptions.PyTeleMonBotHandlerError("Error parsing data")

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
