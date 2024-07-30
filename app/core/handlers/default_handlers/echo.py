#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from telebot.types import Message

from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_handler_session


class EchoHandler(HandlerConstructor):

    def handle(self) -> None:
        """
        Set up the message handler for the bot to echo back any message received.
        This function is decorated with `logged_handler_session` to log the session.

        Args:
            self: The EchoHandler instance.

        Returns:
            None
        """

        @self.bot.message_handler(func=lambda message: True)
        @logged_handler_session
        def echo(message: Message) -> None:
            """
            Handle the message received by the bot.

            Args:
                message (telebot.types.Message): The message received by the bot.

            Raises:
                PyTeleMonBotHandlerError: If there is a ValueError.

            Returns:
                None
            """
            try:
                # Send typing action to the user
                self.bot.send_chat_action(message.chat.id, 'typing')

                # Send the response message to the user
                response: str = 'In a robotic voice: I have checked my notes several times. ' \
                                'Unfortunately, there is no mention of such a command :('
                self.bot.send_message(message.chat.id, text=response)

            except (AttributeError, ValueError) as err:
                # Raise an exception if there is a ValueError while rendering the templates
                raise self.exceptions.PyTeleMonBotHandlerError(f"Failed at @{__name__}: {str(err)}")
