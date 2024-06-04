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

        @self.bot.callback_query_handler(func=lambda call: call.data == 'update_info')
        @logged_inline_handler_session
        def swap(call: CallbackQuery):
            """
            This function handles the callback query for updating information.
            It renders a template with the 'how_update.jinja2' template and edits the message text with the rendered
            template. If there's a ValueError or TemplateError, it raises a PyTeleMonBotHandlerError
            or PyTeleMonBotTemplateError respectively.
            """
            try:
                # Render the 'how_update.jinja2' template with the 'thought_balloon' emoji
                bot_answer = self.jinja.render_templates(
                    'how_update.jinja2',
                    thought_balloon=self.get_emoji('thought_balloon')
                )
                # Edit the message text with the rendered template
                self.bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text=bot_answer,
                    parse_mode="Markdown"
                )
            except ValueError:
                # Raise a PyTeleMonBotHandlerError if there's a ValueError
                raise self.exceptions.PyTeleMonBotHandlerError(self.bot_msg_tpl.VALUE_ERR_TEMPLATE)
            except self.TemplateError:
                # Raise a PyTeleMonBotTemplateError if there's a TemplateError
                raise self.exceptions.PyTeleMonBotTemplateError(self.bot_msg_tpl.TPL_ERR_TEMPLATE)
