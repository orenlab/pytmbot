#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from telebot.types import Message

from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_handler_session


class StartHandler(HandlerConstructor):

    def handle(self):
        @self.bot.message_handler(commands=['help', 'start'])
        @logged_handler_session
        def start(message: Message) -> None:
            """The entry point for starting a dialogue with the bot"""
            try:
                self.bot.send_chat_action(message.chat.id, 'typing')
                main_keyboard = self.keyboard.build_reply_keyboard()
                first_name: str = message.from_user.first_name
                bot_answer: str = self.jinja.render_templates(
                    'index.jinja2',
                    first_name=first_name
                )
                HandlerConstructor._send_bot_answer(
                    self,
                    message.chat.id,
                    text=bot_answer,
                    reply_markup=main_keyboard
                )
            except ValueError:
                raise self.exceptions.PyTeleMonBotHandlerError(
                    self.bot_msg_tpl.VALUE_ERR_TEMPLATE
                )
