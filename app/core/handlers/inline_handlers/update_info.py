#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from telebot.types import CallbackQuery

from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_inline_handler_session


class InlineUpdateInfoHandler(HandlerConstructor):

    def handle(self):
        """
        This method handles the callback query for updating information.
        It sets up a callback query handler for the 'update_info' data.
        When the callback query is received, it renders a template with the 'how_update.jinja2' template and edits
        the message text with the rendered template.

        Raises:
            PyTeleMonBotHandlerError: If there is a ValueError while retrieving swap memory.
            PyTeleMonBotTemplateError: If there is a TemplateError while rendering the template.
        """

        @self.bot.callback_query_handler(func=lambda call: call.data == 'how_update?')
        @logged_inline_handler_session
        def swap(call: CallbackQuery):
            """
            Handles the callback query for updating information.

            This function is called when a callback query with the data 'update_info' is received.
            It renders a template with the 'how_update.jinja2' template and edits the message text
            with the rendered template.

            Args:
                call (CallbackQuery): The callback query object.

            Raises:
                PyTeleMonBotHandlerError: If there is a ValueError while retrieving swap memory.
                PyTeleMonBotTemplateError: If there is a TemplateError while rendering the template.
            """
            try:
                # Define the name of the template to render
                template_name: str = 'how_update.jinja2'

                # Define the emojis to use in the template
                emojis: dict = {'thought_balloon': self.emojis.get_emoji('thought_balloon')}

                # Render the template with the defined emojis
                bot_answer: str = self.jinja.render_templates(template_name, **emojis)

                # Edit the message text with the rendered template
                self.bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text=bot_answer,
                    parse_mode="Markdown"
                )
            except ValueError:
                # Raise an exception if there is a ValueError while retrieving swap memory
                raise self.exceptions.PyTeleMonBotHandlerError(self.bot_msg_tpl.VALUE_ERR_TEMPLATE)
            except self.TemplateError:
                # Raise an exception if there is a TemplateError while rendering the template
                raise self.exceptions.PyTeleMonBotTemplateError(self.bot_msg_tpl.TPL_ERR_TEMPLATE)
