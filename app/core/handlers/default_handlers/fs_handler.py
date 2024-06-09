#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from telebot.types import Message

from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_handler_session


class FileSystemHandler(HandlerConstructor):

    def _get_data(self) -> dict:
        """
        This method uses the psutil library to gather data on the local filesystem.

        Returns:
            dict: A dictionary containing information about the disk usage.
        """
        # Retrieve disk usage information using psutil
        data = self.psutil_adapter.get_disk_usage()

        # Return the dictionary containing the disk usage information
        return data

    def _compile_message(self) -> str:
        """
        Compiles the message to be sent to the bot based on the filesystem data.

        This function retrieves the filesystem data using the `_get_data` method and
        compiles it into a message using a Jinja2 template.

        Args:
            self (FileSystemHandler): Instance of the FileSystemHandler class.

        Returns:
            str: The compiled message to be sent to the bot.

        Raises:
            PyTeleMonBotHandlerError: If there is an error parsing the data.
        """
        try:
            # Get the filesystem data
            context: dict = self._get_data()

            template_name: str = 'fs.jinja2'

            emojis: dict[str, str] = {
                'thought_balloon': self.emojis.get_emoji('thought_balloon'),
                'floppy_disk': self.emojis.get_emoji('floppy_disk'),
                'minus': self.emojis.get_emoji('minus'),
            }

            # Render the template with the context data
            return self.jinja.render_templates(template_name, context=context, **emojis)

        except ValueError:
            # Raise an exception if there is an error parsing the data
            raise self.exceptions.PyTeleMonBotHandlerError("Error parsing data")

    def handle(self) -> None:
        """
        Handle the "File system" message and send the file system info.

        This function sets up a message handler for the "File system" regexp.
        When a message with this regexp is received, it sends a typing action to the chat,
        compiles the message using the `_compile_message` method,
        and sends the compiled message as a bot answer.

        Raises:
            PyTeleMonBotHandlerError: If there is a ConnectionError while sending the chat action.
        """

        @self.bot.message_handler(regexp="File system")
        @logged_handler_session
        def get_fs(message: Message) -> None:
            """
            Get file system info.

            This function handles the 'File system' message, sends a typing action to the chat, compiles the message
            using the `_compile_message` method, and sends the compiled message as a bot answer.

            Args:
                message (Message): The message received by the bot.

            Raises:
                PyTeleMonBotHandlerError: If there is a ConnectionError while sending the chat action.
            """
            try:
                # Send a typing action to the chat
                self.bot.send_chat_action(message.chat.id, 'typing')

                # Compile the message using the `_compile_message` method
                bot_answer: str = self._compile_message()

                # Send the bot answer
                HandlerConstructor._send_bot_answer(
                    self,
                    message.chat.id,
                    text=bot_answer
                )
            except ConnectionError:
                # Raise an exception if there is a ConnectionError while sending the chat action
                raise self.exceptions.PyTeleMonBotHandlerError(
                    self.bot_msg_tpl.VALUE_ERR_TEMPLATE
                )
