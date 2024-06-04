#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from telebot.types import Message

from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_handler_session


class EchoHandler(HandlerConstructor):

    def handle(self):
        @self.bot.message_handler(func=lambda message: True)
        @logged_handler_session
        def start(message: Message) -> None:
            """The entry point for starting a dialogue with the bot"""
            try:
                self.bot.send_chat_action(message.chat.id, 'typing')
                self.bot.send_message(message.chat.id, 'In a robotic voice: I have checked my notes several times. '
                                                       'Unfortunately, there is no mention of such a command :('
                                      )
            except ValueError:
                raise self.exceptions.PyTeleMonBotHandlerError(
                    self.bot_msg_tpl.VALUE_ERR_TEMPLATE
                )
