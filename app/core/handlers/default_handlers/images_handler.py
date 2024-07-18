#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from telebot.types import Message

from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_handler_session


class ImagesHandler(HandlerConstructor):

    def handle(self):
        """
        Handles the 'Back to main menu' message.
        """

        @self.bot.message_handler(regexp="Images")
        @logged_handler_session
        def docker_images(message: Message) -> None:
            """
            Handler for the 'Images' message.

            This function is triggered when the user sends a message that matches the regexp "Images".
            It sends a typing action to the user, builds a main keyboard, gets the user's first name, renders a
            template,and sends the rendered template to the user with the main keyboard.

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
                reply_keyboard = self.keyboard.build_reply_keyboard(keyboard_type='docker_keyboard')

                # Send the bot answer to the user with the main keyboard
                self.bot.send_message(
                    message.chat.id,
                    text="Images handler in development... I apologize for the inconvenience.",
                    reply_markup=reply_keyboard
                )
            except ValueError:
                # Raise an exception if there is a ValueError while rendering the templates
                raise self.exceptions.PyTeleMonBotHandlerError(
                    self.bot_msg_tpl.VALUE_ERR_TEMPLATE
                )
