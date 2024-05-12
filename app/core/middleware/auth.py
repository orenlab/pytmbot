#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""

from telebot.handler_backends import (
    BaseMiddleware,
    CancelUpdate
)
from telebot.types import Message
from app import (
    config,
    bot,
    bot_logger
)
from app.core.settings.loggers import MessageTpl


class AllowedUser(BaseMiddleware):
    """Custom middleware class that check allowed users"""

    def __init__(self) -> None:
        """Initialize the middleware"""
        super().__init__()
        self.bot_msg_tpl = MessageTpl()
        self.update_types = ['message']  # Needed for correctly work middleware

    def pre_process(self, message: Message, data):
        """Check allowed users"""
        if message.from_user.id in config.allowed_user_ids:
            bot_logger.info(
                self.bot_msg_tpl.ACCESS_SUCCESS.format(
                    message.from_user.username,
                    message.from_user.id,
                )
            )
        else:
            bot.send_chat_action(message.chat.id, 'typing')
            bot_logger.error(
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

    def post_process(self, message: Message, data, exception):  # Not needed in this case, but needed for method
        """Method need to correctly work middleware"""
