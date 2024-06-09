#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from typing import Dict, Union

from telebot.types import Message

from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_handler_session


class MemoryHandler(HandlerConstructor):
    """Class for handling memory usage"""

    def _get_data(self) -> tuple:
        """
        Get memory data using psutil.

        Returns:
            A tuple containing memory data.
        """
        # Use the psutil_adapter to get memory data
        data = self.psutil_adapter.get_memory()

        return data

    def _compile_message(self) -> tuple:
        """
        Compile the message to be sent to the bot.

        This function uses psutil to gather data on the memory load. It returns a tuple containing memory data.

        Raises:
            PyTeleMonBotHandlerError: If there is an error parsing the data.

        Returns:
            tuple: The compiled message to send to the bot.
        """
        try:
            # Use the psutil_adapter to get memory data
            # This method is responsible for retrieving memory data using psutil
            # and returning it as a tuple
            context = self._get_data()

            # Return the memory data as a tuple
            return context

        except ValueError:
            # If there is an error parsing the data, raise a PyTeleMonBotHandlerError
            # with a specific error message
            raise self.exceptions.PyTeleMonBotHandlerError(
                self.bot_msg_tpl.VALUE_ERR_TEMPLATE
            )

    def _get_answer(self) -> str:
        """
        Parse the answer to a template.

        This function tries to compile the message to be sent to the bot using the _compile_message method.
        If the compilation is successful, it renders the 'memory.jinja2' template with the compiled message.
        If there is a TemplateError during rendering, it raises a PyTeleMonBotTemplateError.

        Args:
            self (MemoryHandler): The instance of the MemoryHandler class.

        Returns:
            str: The compiled message to be sent to the bot.

        Raises:
            PyTeleMonBotTemplateError: If there is a TemplateError during rendering.
        """
        try:
            # Compile the message to be sent to the bot
            context: tuple = self._compile_message()

            # Define the template name for rendering
            template_name: str = 'memory.jinja2'

            emojis: Dict[str, Union[str, str]] = {
                'thought_balloon': self.emojis.get_emoji('thought_balloon'),  # Get the thought balloon emoji
                'abacus': self.emojis.get_emoji('abacus'),  # Get the abacus emoji
            }

            # Render the 'memory.jinja2' template with the compiled message
            bot_answer: str = self.jinja.render_templates(template_name, **emojis, context=context)

            # Return the compiled message
            return bot_answer

        except self.TemplateError:
            # Raise a PyTeleMonBotTemplateError if there is a TemplateError during rendering
            raise self.exceptions.PyTeleMonBotTemplateError(
                self.bot_msg_tpl.TPL_ERR_TEMPLATE
            )

    def handle(self):
        """
        Method to handle memory load information.

        This method sets up a message handler for the "Memory load" regex pattern.
        When a message with this pattern is received, it sends a typing action to the chat,
        retrieves the answer using the `_get_answer` method, and sends the answer along
        with an inline button using the `HandlerConstructor._send_bot_answer` method.

        Raises:
            PyTeleMonBotConnectionError: If there is a ConnectionError while sending the typing action.
        """

        @self.bot.message_handler(regexp="Memory load")
        @logged_handler_session
        def get_memory(message: Message) -> None:
            """
            Main handler for the Memory info.

            Args:
                message (Message): The message received by the bot.

            Raises:
                PyTeleMonBotConnectionError: If there is a ConnectionError while sending the typing action.
            """
            try:
                self.bot.send_chat_action(message.chat.id, 'typing')
                bot_answer = self._get_answer()

                inline_button = self.keyboard.build_inline_keyboard(
                    "Swap info",
                    "swap_info"
                )

                HandlerConstructor._send_bot_answer(
                    self,
                    message.chat.id,
                    text=bot_answer,
                    reply_markup=inline_button
                )
            except ConnectionError:
                raise self.exceptions.PyTeleMonBotConnectionError(
                    self.bot_msg_tpl.VALUE_ERR_TEMPLATE
                )
