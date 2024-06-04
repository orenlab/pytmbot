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
        Handle 'About me' message.

        This function sets up a message handler for the bot to respond to messages
        containing the phrase "About me". When such a message is received, it sends
        a typing action to the chat, renders a template with the user's first name
        and the current application version, and sends the rendered template as a
        bot answer.

        Raises:
            PyTeleMonBotHandlerError: If there is a ValueError while rendering the
            template.
        """

        @self.bot.message_handler(regexp="About me")
        @logged_handler_session
        def about_bot_handler(message: Message) -> None:
            """
            Handle 'About me' message.

            Args:
                message (Message): The message received by the bot.

            Raises:
                PyTeleMonBotHandlerError: If there is a ValueError while rendering
                the template.
            """
            try:
                # Send typing action to chat
                self.bot.send_chat_action(message.chat.id, 'typing')

                # Get user's first name
                user_first_name = message.from_user.first_name

                # Render template with user's first name and current app version
                bot_answer = self.jinja.render_templates(
                    'about_bot.jinja2',
                    first_name=user_first_name,
                    current_app_version=__version__
                )

                # Send bot answer
                HandlerConstructor._send_bot_answer(
                    self,
                    message.chat.id,
                    text=bot_answer,
                    parse_mode='Markdown',
                )
            except ValueError:
                # Raise error if there is a ValueError while rendering the template
                error_msg = self.bot_msg_tpl.VALUE_ERR_TEMPLATE
                raise self.exceptions.PyTeleMonBotHandlerError(error_msg)
