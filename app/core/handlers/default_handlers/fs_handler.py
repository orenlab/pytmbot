#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from app.core.handlers.handler import Handler
from app import build_logger
from app.core.adapters.psutil_adapter import PsutilAdapter


class FileSystemHandler(Handler):
    def __init__(self, bot):
        super().__init__(bot)
        self.log = build_logger(__name__)
        self.psutil_adapter = PsutilAdapter()

    def handle(self):
        @self.bot.message_handler(regexp="File system")
        def get_fs(message) -> None:
            """
            Get file system info
            """
            try:
                self.log.info(self.bot_msg_tpl.HANDLER_START_TEMPLATE.format(
                    "File system handler",
                    message.from_user.username,
                    message.from_user.id,
                    message.from_user.language_code,
                    message.from_user.is_bot
                ))
                context = self.api_data.get_metrics('fs')
                context_process = []
                for disk in context:
                    context_process += {
                        "device_name": disk["device_name"],
                        "used": self.format_bytes(disk["used"]),
                        "percent": disk["percent"],
                        "free": self.format_bytes(disk["free"]),
                    },
                tpl = self.jinja.get_template('fs.jinja2')
                bot_answer = tpl.render(
                    thought_balloon=self.get_emoji('thought_balloon'),
                    floppy_disk=self.get_emoji('floppy_disk'),
                    minus=self.get_emoji('minus'),
                    context=context_process
                )
                self.bot.send_message(message.chat.id, text=bot_answer)
            except ValueError as err:
                raise self.exceptions.PyTeleMonBotHandlerError(self.bot_msg_tpl.VALUE_ERR_TEMPLATE) from err
            except self.TemplateError as err_tpl:
                raise self.exceptions.PyTeleMonBotTemplateError(self.bot_msg_tpl.TPL_ERR_TEMPLATE) from err_tpl
