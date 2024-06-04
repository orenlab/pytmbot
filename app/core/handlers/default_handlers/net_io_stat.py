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

    def _get_data(self):
        """
        Get network card IO statistics using psutil.

        This function uses the psutil_adapter to gather data on the network card IO statistics.
        It returns the gathered data.

        Returns:
            dict: A dictionary containing the network card IO statistics.
        """
        # Use psutil to gather data on the network card IO statistics
        data = self.psutil_adapter.get_net_io_counters()

        return data

    def _compile_message(self) -> str:
        """
        Compile the message to send to the bot.

        This method uses Jinja2 templates to generate a message with network card IO statistics.
        It renders the 'net_io.jinja2' template and passes the necessary variables.

        Returns:
            str: The compiled message to send to the bot.

        Raises:
            PyTeleMonBotHandlerError: If there is an error parsing the data.
        """
        try:
            # Render the 'net_io.jinja2' template and pass the necessary variables
            bot_answer: str | None = self.jinja.render_templates(
                'net_io.jinja2',
                thought_balloon=self.get_emoji('thought_balloon'),  # Thought balloon emoji
                up_left_arrow=self.get_emoji('up-left_arrow'),  # Up left arrow emoji
                up_right_arrow=self.get_emoji('up-right_arrow'),  # Up right arrow emoji
                globe_showing_europe_africa=self.get_emoji('globe_showing_Europe-Africa'),  # Globe emoji
                hugging_face=self.get_emoji('smiling_face_with_open_hands'),  # Hugging face emoji
                context=self._get_data()  # Network card IO statistics
            )
            return bot_answer
        except ValueError:
            # Raise an exception if there is an error parsing the data
            self.exceptions.PyTeleMonBotHandlerError("Error parsing data")

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
                HandlerConstructor._send_bot_answer(
                    self,
                    message.chat.id,
                    text=bot_answer
                )
            except ValueError:
                # Raise an exception if there is an error parsing the data
                raise self.exceptions.PyTeleMonBotHandlerError(
                    self.bot_msg_tpl.VALUE_ERR_TEMPLATE
                )
