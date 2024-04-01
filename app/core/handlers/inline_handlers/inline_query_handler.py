#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from telebot import types

from app.core.adapters.psutil_adapter import PsutilAdapter

from app import logger

from app.core.handlers.handler import Handler


class InlineQueryHandler(Handler):
    def __init__(self, bot):
        super().__init__(bot)
        self.log = logger
        self.psutil_adapter = PsutilAdapter()

    def handle(self):

        @self.bot.callback_query_handler(func=lambda call: call.data == 'docker_image_update')
        def docker_image_update(call: types.CallbackQuery):
            """
            Get callback query - docker image update check
            """
            try:
                self.log.info(
                    self.bot_msg_tpl.HANDLER_START_TEMPLATE.format("callback_query_handler['docker_image_update']"))
                self.bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text="Test callback_query_handler['docker_image_update']"
                )

            except ValueError:
                raise self.exceptions.PyTeleMonBotHandlerError(self.bot_msg_tpl.VALUE_ERR_TEMPLATE)
            except self.TemplateError:
                raise self.exceptions.PyTeleMonBotTemplateError(self.bot_msg_tpl.TPL_ERR_TEMPLATE)
