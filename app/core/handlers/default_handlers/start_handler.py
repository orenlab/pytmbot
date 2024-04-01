#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from app.core.handlers.handler import Handler
from app import logger
from telebot.types import Message


class StartHandler(Handler):
    def __init__(self, bot):
        super().__init__(bot)
        self.log = logger

    def handle(self):
        @self.bot.message_handler(commands=['help', 'start'])
        def start(message: Message) -> None:
            """
            The entry point for starting a dialogue with the bot
            """
            try:
                self.log.info(self.bot_msg_tpl.HANDLER_START_TEMPLATE.format(
                    message.from_user.username,
                    message.from_user.id,
                    message.from_user.language_code,
                    message.from_user.is_bot
                ))
                main_keyboard = self.keyboard.build_reply_keyboard()
                first_name: str = message.from_user.first_name
                bot_answer: str = self.jinja.render_templates(
                    'index.jinja2',
                    first_name=first_name
                )
                self.bot.send_message(
                    message.chat.id,
                    text=bot_answer,
                    reply_markup=main_keyboard
                )
            except ValueError:
                raise self.exceptions.PyTeleMonBotHandlerError(
                    self.bot_msg_tpl.VALUE_ERR_TEMPLATE
                )
