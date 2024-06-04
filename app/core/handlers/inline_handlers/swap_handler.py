#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
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
        def swap(call: CallbackQuery):
            """
            This method handles the callback query when the data is 'swap_info'.
            It retrieves swap memory information using the `psutil_adapter` object.
            It then renders a template using the `jinja` object and the retrieved context.
            Finally, it edits the message text with the rendered template.

            Raises:
                PyTeleMonBotHandlerError: If there is a ValueError while retrieving swap memory.
                PyTeleMonBotTemplateError: If there is a TemplateError while rendering the template.
            """
            try:
                # Retrieve swap memory information
                context = self.psutil_adapter.get_swap_memory()

                # Render the template with the retrieved context
                bot_answer = self.jinja.render_templates(
                    'swap.jinja2',
                    thought_balloon=self.get_emoji('thought_balloon'),
                    paperclip=self.get_emoji('paperclip'),
                    context=context
                )

                # Edit the message text with the rendered template
                self.bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text=bot_answer
                )

            # Handle ValueError and TemplateError exceptions
            except ValueError:
                raise self.exceptions.PyTeleMonBotHandlerError(self.bot_msg_tpl.VALUE_ERR_TEMPLATE)
            except self.TemplateError:
                raise self.exceptions.PyTeleMonBotTemplateError(self.bot_msg_tpl.TPL_ERR_TEMPLATE)
