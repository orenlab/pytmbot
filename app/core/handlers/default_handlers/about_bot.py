#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from telebot.types import Message

from app import __version__
from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_handler_session


class AboutBotHandler(HandlerConstructor):

    def handle(self):
        """
        Set up a message handler for the bot to respond to messages containing the phrase "About me".

        When such a message is received, it sends a typing action to the chat, renders a template with the user's first
        name and the current application version, and sends the rendered template as a bot answer.

        Raises:
            PyTeleMonBotHandlerError: If there is a ValueError while rendering the template.
        """

        @self.bot.message_handler(regexp="About me")
        @logged_handler_session
        def about_bot_handler(message: Message) -> None:
            """
            Handle 'About me' message.

            Args:
                message (Message): The message received by the bot.

            Raises:
                PyTeleMonBotHandlerError: If there is a ValueError while rendering the template.
            """
            try:
                # Get the user's first name from the message
                user_first_name = message.from_user.first_name

                # Send a typing action to the chat
                self.bot.send_chat_action(message.chat.id, 'typing')

                # Render the template with the user's first name and the current application version
                template_variables: dict[str, str] = {
                    'first_name': user_first_name,
                    'current_app_version': __version__
                }
                bot_answer = self.jinja.render_templates('about_bot.jinja2', context=template_variables)

                # Send the rendered template as a bot answer
                self._send_bot_answer(
                    message.chat.id,
                    text=bot_answer,
                    parse_mode='Markdown'
                )
            except ValueError:
                # Raise an exception if there is a ValueError while rendering the template
                error_message = self.bot_msg_tpl.VALUE_ERROR_TEMPLATE
                raise self.exceptions.PyTeleMonBotHandlerError(error_message)
