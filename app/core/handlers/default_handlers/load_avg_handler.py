#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from telebot.types import Message

from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_handler_session


class LoadAvgHandler(HandlerConstructor):
    """Class to handle loading the average"""

    def _get_data(self) -> tuple:
        """
        Use psutil to gather data on the processor load.

        Returns:
            A tuple containing the load average for the last 1 minute, 5 minutes, and 15 minutes.
        """
        # Use psutil to gather data on the processor load
        data = self.psutil_adapter.get_load_average()

        return data

    def _compile_message(self) -> str:
        """
        Compiles a message to send to the bot with load average data.

        This function compiles the load average data retrieved using the _get_data method,
        sets up template variables for emojis, renders the template, and returns the bot's answer.

        Args:
            self (LoadAvgHandler): Instance of the LoadAvgHandler class.

        Returns:
            str: The compiled message to send to the bot.

        Raises:
            PyTeleMonBotHandlerError: If there is an error parsing the data.
        """
        try:
            # Getting the load average data and rounding it up
            load_average_data = self.round_up_tuple(self._get_data())

            # Setting up the template variables for emojis
            emojis: dict[str, dict | str] = {
                'thought_balloon': self.get_emoji('thought_balloon'),
                'desktop_computer': self.get_emoji('desktop_computer'),
            }

            # Rendering the template to get the bot's answer
            bot_answer = self.jinja.render_templates('load_average.jinja2', context=load_average_data, **emojis)

            # Returning the bot's answer
            return bot_answer
        except ValueError:
            # Handling error if there is an issue parsing the data
            raise self.exceptions.PyTeleMonBotHandlerError("Error parsing data")

    def handle(self) -> None:
        """
        Methods to handle Load average data
        """

        @self.bot.message_handler(regexp="Load average")
        @logged_handler_session
        def get_average(message: Message) -> None:
            """
            Main load average handler

            This function handles the "Load average" message and sends the compiled message to the bot.

            Args:
                message (Message): The message object received from the bot.

            Raises:
                PyTeleMonBotHandlerError: If there is an error parsing the data.
            """
            try:
                # Send a typing action to indicate that the bot is processing the message
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
