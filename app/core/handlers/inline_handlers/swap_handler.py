#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from telebot.types import CallbackQuery

from app.core.adapters.psutil_adapter import PsutilAdapter
from app.core.handlers.handler import Handler
from app.core.logs import logged_inline_handler_session


class InlineSwapHandler(Handler):
    def __init__(self, bot):
        super().__init__(bot)
        self.psutil_adapter = PsutilAdapter()

    def handle(self):
        @self.bot.callback_query_handler(func=lambda call: call.data == 'swap_info')
        @logged_inline_handler_session
        def swap(call: CallbackQuery):
            """Get callback query - swap information from psutil"""
            try:
                context = self.psutil_adapter.get_swap_memory()  # need refactoring code
                bot_answer = self.jinja.render_templates(
                    'swap.jinja2',
                    thought_balloon=self.get_emoji('thought_balloon'),
                    paperclip=self.get_emoji('paperclip'),
                    context=context
                )
                self.bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text=bot_answer
                )
            except ValueError:
                raise self.exceptions.PyTeleMonBotHandlerError(self.bot_msg_tpl.VALUE_ERR_TEMPLATE)
            except self.TemplateError:
                raise self.exceptions.PyTeleMonBotTemplateError(self.bot_msg_tpl.TPL_ERR_TEMPLATE)
