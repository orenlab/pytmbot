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
        @self.bot.message_handler(regexp="About me")
        @logged_handler_session
        def start(message: Message) -> None:
            """About bot handler"""
            try:
                self.bot.send_chat_action(message.chat.id, 'typing')
                first_name: str = message.from_user.first_name
                bot_answer: str = self.jinja.render_templates(
                    'about_bot.jinja2',
                    first_name=first_name,
                    current_app_version=__version__
                )
                HandlerConstructor._send_bot_answer(
                    self,
                    message.chat.id,
                    text=bot_answer,
                    parse_mode='Markdown',
                )
            except ValueError:
                raise self.exceptions.PyTeleMonBotHandlerError(
                    self.bot_msg_tpl.VALUE_ERR_TEMPLATE
                )
