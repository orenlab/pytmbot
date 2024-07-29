#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from telebot.types import Message, LinkPreviewOptions

from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_handler_session


class StartHandler(HandlerConstructor):

    def handle(self):
        """
        Handle the start command and initiate a dialogue with the bot.

        Args:
            self: StartHandler object.

        Returns:
            None
        """

        @self.bot.message_handler(commands=['help', 'start'])
        @logged_handler_session
        def start(message: Message) -> None:
            """
            The entry point for starting a dialogue with the bot.

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

                template_name: str = 'index.jinja2'

                # Render the templates and get the bot answer
                bot_answer: str = self.jinja.render_templates(
                    template_name,
                    first_name=first_name
                )

                # Send the bot answer to the user with the main keyboard
                self.bot.send_message(
                    message.chat.id,
                    text=bot_answer,
                    reply_markup=main_keyboard,
                    parse_mode="Markdown",
                    link_preview_options=LinkPreviewOptions(is_disabled=True)
                )
            except ValueError:
                # Raise an exception if there is a ValueError while rendering the templates
                raise self.exceptions.PyTeleMonBotHandlerError(
                    self.bot_msg_tpl.VALUE_ERR_TEMPLATE
                )
