#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from telebot import types

from app.core.adapters.psutil_adapter import PsutilAdapter
from app.core.adapters.docker_adapter import DockerImageUpdateChecker

from app import build_logger

from app.core.handlers.handler import Handler


class InlineQueryHandler(Handler):
    def __init__(self, bot):
        super().__init__(bot)
        self.log = build_logger(__name__)
        self.psutil_adapter = PsutilAdapter()

    def handle(self):
        @self.bot.callback_query_handler(func=lambda call: call.data == 'history_load')
        def history_load(call: types.CallbackQuery):
            """
            Get callback query - history load average
            """
            try:
                if call.message.from_user.id in self.config.ALLOWED_USER_IDS:
                    self.log.info(
                        self.bot_msg_tpl.INFO_USER_SESSION_START_TEMPLATE.format(
                            call.message.from_user.username,
                            call.message.from_user.id,
                            "callback_query_handler['history_load']"
                        )
                    )
                    self.bot.edit_message_text(
                        chat_id=call.message.chat.id,
                        message_id=call.message.message_id,
                        text="Test callback_query_handler['history_load']"
                    )
                else:
                    self.log.error(
                        self.bot_msg_tpl.ERROR_ACCESS_LOG_TEMPLATE.format(
                            call.message.from_user.username,
                            call.message.from_user.id,
                            call.message.from_user.language_code,
                            call.message.from_user.is_bot
                        )
                    )
                    self.bot.edit_message_text(
                        chat_id=call.message.chat.id,
                        message_id=call.message.message_id,
                        text=self.bot_msg_tpl.ERROR_USER_BLOCKED_TEMPLATE
                    )
            except ValueError as err:
                raise self.exceptions.PyTeleMonBotHandlerError(self.bot_msg_tpl.VALUE_ERR_TEMPLATE) from err
            except self.TemplateError as err_tpl:
                raise self.exceptions.PyTeleMonBotTemplateError(self.bot_msg_tpl.TPL_ERR_TEMPLATE) from err_tpl

        @self.bot.callback_query_handler(func=lambda call: call.data == 'docker_image_update')
        def docker_image_update(call: types.CallbackQuery):
            """
            Get callback query - docker image update check
            """
            try:
                if call.message.from_user.id in self.config.ALLOWED_USER_IDS:
                    self.log.info(
                        self.bot_msg_tpl.INFO_USER_SESSION_START_TEMPLATE.format(
                            call.message.from_user.username,
                            call.message.from_user.id,
                            "callback_query_handler['docker_image_update']"
                        )
                    )
                    b = []
                    up = DockerImageUpdateChecker('nicolargo/glances')
                    b += {up.check_updates()}
                    bot_answer = b
                    self.bot.edit_message_text(
                        chat_id=call.message.chat.id,
                        message_id=call.message.message_id,
                        text=bot_answer
                    )
                else:
                    self.log.error(
                        self.bot_msg_tpl.ERROR_ACCESS_LOG_TEMPLATE.format(
                            call.message.from_user.username,
                            call.message.from_user.id,
                            call.message.from_user.language_code,
                            call.message.from_user.is_bot
                        )
                    )
                    self.bot.edit_message_text(
                        chat_id=call.message.chat.id,
                        message_id=call.message.message_id,
                        text=self.bot_msg_tpl.ERROR_USER_BLOCKED_TEMPLATE
                    )
            except ValueError as err:
                raise self.exceptions.PyTeleMonBotHandlerError(self.bot_msg_tpl.VALUE_ERR_TEMPLATE) from err
            except self.TemplateError as err_tpl:
                raise self.exceptions.PyTeleMonBotTemplateError(self.bot_msg_tpl.TPL_ERR_TEMPLATE) from err_tpl
