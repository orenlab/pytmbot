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
)
from app.core.logs import bot_logger
from app.core.settings.loggers import MessageTpl


class AllowedUser(BaseMiddleware):
    """
    Custom middleware class that checks if the user is allowed to access the bot.
    """

    def __init__(self) -> None:
        """
        Initialize the middleware.

        This method initializes the middleware by setting the bot message template
        and the update types.

        Returns:
            None
        """
        super().__init__()
        self.bot_msg_tpl = MessageTpl()
        self.update_types = ['message', 'inline_query']

    def pre_process(self, message: Message, data) -> CancelUpdate:
        """
        Check if the user is allowed to access the bot.

        Args:
            message (Message): Object from Telebot containing user information.
            data (): Additional data from Telebot.

        Returns:
            CancelUpdate: An instance of the CancelUpdate class.
        """
        # Extract user information from the message
        user_id = message.from_user.id
        user_name = message.from_user.username
        chat_id = message.chat.id

        # Check if the user is allowed
        if user_id in config.allowed_user_ids:
            # Log the successful access
            bot_logger.info(
                self.bot_msg_tpl.ACCESS_SUCCESS.format(user_name, user_id)
            )
        else:
            # Send a typing action to indicate that the bot is processing
            bot.send_chat_action(chat_id, 'typing')

            # Log the failed access
            error_message = self.bot_msg_tpl.ERROR_ACCESS_LOG_TEMPLATE.format(
                user_name, user_id, message.from_user.language_code, message.from_user.is_bot
            )
            bot_logger.error(error_message)

            # Send a message to the user indicating that they are blocked
            blocked_message = self.bot_msg_tpl.ERROR_USER_BLOCKED_TEMPLATE
            bot.send_message(chat_id, blocked_message)

            # Cancel any further processing of the message
            return CancelUpdate()

    def post_process(self, message: Message, data, exception) -> None:
        """
        This method is a part of the middleware process and is not needed in this case.
        However, it is required for the correct functioning of the middleware.

        Args:
            message (Message): Object from Telebot containing user information.
            data (): Additional data from Telebot.
            exception: Exception that occurred during the middleware process.

        Returns:
            None
        """
