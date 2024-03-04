from telebot.handler_backends import BaseMiddleware
from telebot.handler_backends import CancelUpdate
from telebot.types import Message
from app import config, bot, build_logger
from app.core.settings.message_tpl import MessageTpl


class AllowedUser(BaseMiddleware):
    def __init__(self) -> None:
        super().__init__()
        self.log = build_logger(__name__)
        self.bot_msg_tpl = MessageTpl()
        self.update_types = ['message']

    def pre_process(self, message: Message, data):
        if message.from_user.id in config.ALLOWED_USER_IDS:
            self.log.info(
                self.bot_msg_tpl.INFO_USER_SESSION_START_TEMPLATE.format(
                    message.from_user.username,
                    message.from_user.id,
                    ""
                )
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
            bot.send_message(
                message.chat.id,
                self.bot_msg_tpl.ERROR_USER_BLOCKED_TEMPLATE
            )
            return CancelUpdate()

    def post_process(self, message: Message, data, exception):
        pass
