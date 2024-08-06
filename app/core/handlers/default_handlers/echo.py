#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
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
                # Define emojis for rendering
                emojis: dict = {
                    'thought_balloon': self.emojis.get_emoji('thought_balloon'),
                }
                # Send the response message to the user
                bot_answer = self.jinja.render_templates('b_echo.jinja2', first_name=message.from_user.first_name,
                                                         **emojis)
                self.bot.send_message(message.chat.id, text=bot_answer)

            except (AttributeError, ValueError) as err:
                # Raise an exception if there is a ValueError while rendering the templates
                raise self.exceptions.PyTeleMonBotHandlerError(f"Failed at @{__name__}: {str(err)}")
