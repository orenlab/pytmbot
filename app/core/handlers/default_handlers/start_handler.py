#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from app.core.handlers.handler import Handler
from app import build_logger


class StartHandler(Handler):
    def __init__(self, bot):
        super().__init__(bot)
        self.log = build_logger(__name__)

    def handle(self):
        @self.bot.message_handler(commands=['help', 'start'])
        def start(message) -> None:
            """
            The entry point for starting a dialogue with the bot
            """
            try:
                if message.from_user.id in self.config.ALLOWED_USER_IDS:
                    self.log.info(
                        self.bot_msg_tpl.INFO_USER_SESSION_START_TEMPLATE.format(
                            message.from_user.username,
                            message.from_user.id,
                            "start"
                        )
                    )
                    main_keyboard = self.keyboard.build_reply_keyboard()
                    first_name: str = message.from_user.first_name
                    tpl = self.jinja.get_template('index.jinja2')
                    bot_answer: str = tpl.render(first_name=first_name)
                    self.bot.send_message(
                        message.chat.id,
                        text=bot_answer,
                        reply_markup=main_keyboard
                    )
                else:
                    self.log.error(
                        self.bot_msg_tpl.ERROR_ACCESS_LOG_TEMPLATE.format(
                            message.from_user.username,
                            message.from_user.id,
                            message.from_user.language_code,
                            message.from_user.is_bot
                        )
                    )
                    self.bot.send_message(
                        message.chat.id,
                        self.bot_msg_tpl.ERROR_USER_BLOCKED_TEMPLATE
                    )
            except ValueError as err:
                raise self.exceptions.PyTeleMonBotHandlerError(
                    self.bot_msg_tpl.VALUE_ERR_TEMPLATE
                ) from err
            except self.TemplateError as err_tpl:
                raise self.exceptions.PyTeleMonBotTemplateError(
                    self.bot_msg_tpl.TPL_ERR_TEMPLATE
                ) from err_tpl
