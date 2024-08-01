#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot.types import Message

from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_handler_session


class BackHandler(HandlerConstructor):

    def handle(self):
        """
        Handles the 'Back to main menu' message.
        """

        @self.bot.message_handler(regexp="Back to main menu")
        @self.bot.message_handler(commands=['back'])
        @logged_handler_session
        def back_to_main_menu(message: Message) -> None:
            """
            Handler for the 'Back to main menu' message.

            This function is triggered when the user sends a message that matches the regexp "Back to main menu".
            It sends a typing action to the user, builds a main keyboard, gets the user's first name,
            renders a template, and sends the rendered template to the user with the main keyboard.

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
                main_keyboard = self.keyboard.build_reply_keyboard()

                # Get the first name of the user
                first_name: str = message.from_user.first_name

                template_name: str = 'back.jinja2'

                # Define the emojis to be used in the template
                emojis = {
                    'thought_balloon': self.emojis.get_emoji('thought_balloon'),
                }

                # Render the templates and get the bot answer
                bot_answer: str = self.jinja.render_templates(
                    template_name,
                    **emojis,
                    first_name=first_name
                )

                # Send the bot answer to the user with the main keyboard
                self.bot.send_message(
                    message.chat.id,
                    text=bot_answer,
                    reply_markup=main_keyboard
                )
            except (AttributeError, ValueError) as err:
                # Raise an exception if there is a ValueError while rendering the templates
                raise self.exceptions.PyTeleMonBotHandlerError(f"Failed at @{__name__}: {str(err)}")
