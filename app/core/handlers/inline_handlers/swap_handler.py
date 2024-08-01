#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from typing import Dict

from telebot.types import CallbackQuery

from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_inline_handler_session


class InlineSwapHandler(HandlerConstructor):

    def handle(self):
        """
        This method sets up a callback query handler for the bot.
        The handler checks if the callback query data is 'swap_info'.
        If it is, it calls the `swap` method to handle the callback query.
        """

        @self.bot.callback_query_handler(func=lambda call: call.data == 'swap_info')
        @logged_inline_handler_session
        def swap(call: CallbackQuery) -> None:
            """
            Handle the callback query when the data is 'swap_info'.

            Retrieves swap memory information using the `psutil_adapter` object.
            Renders a template using the `jinja` object and the retrieved context.
            Edits the message text with the rendered template.

            Raises:
                PyTeleMonBotHandlerError: If there is a ValueError while retrieving swap memory.
                PyTeleMonBotTemplateError: If there is a TemplateError while rendering the template.
            """
            try:
                # Retrieve swap memory information
                context = self.psutil_adapter.get_swap_memory()

                # Render the 'swap.jinja2' template
                template_name: str = 'swap.jinja2'

                # Define the template context
                emojis: Dict[str, str] = {
                    'thought_balloon': self.emojis.get_emoji('thought_balloon'),  # Emoji for thought balloon
                    'paperclip': self.emojis.get_emoji('paperclip'),  # Emoji for paperclip
                }

                # Render the template with the retrieved context
                bot_answer: str = self.jinja.render_templates(template_name, context=context, **emojis)

                # Edit the message text with the rendered template
                self.bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text=bot_answer
                )
            except (AttributeError, ValueError) as err:
                # Raise an exception if there is a ValueError while rendering the templates
                raise self.exceptions.PyTeleMonBotHandlerError(f"Failed at @{__name__}: {str(err)}")
