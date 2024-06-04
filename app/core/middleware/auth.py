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
    """Custom middleware class that check allowed users"""

    def __init__(self) -> None:
        """
        Initialize the middleware.

        This method initializes the middleware by setting the bot message template
        and the update types.

        Returns:
            None
        """
        # Call the parent class's __init__ method
        super().__init__()

        # Set the bot message template
        self.bot_msg_tpl = MessageTpl()

        # Set the update types
        self.update_types = ['message', 'inline_query']

    def pre_process(self, message: Message, data) -> CancelUpdate:
        """
        Check if the user is allowed to access the bot.

        Args:
            message (Message): Object from Telebot containing user information.
            data (): Additional data from Telebot.

        Returns:
            CancelUpdate: An instance of the CancelUpdate class.

        This function checks if the user is allowed to access the bot based on their ID.
        If the user is allowed, it logs a success message.
        If the user is not allowed, it sends a typing action, logs an error message,
        and sends a blocked user message to the user.
        It then returns a CancelUpdate object to stop further processing of the message.
        """
        # Check if the user is allowed
        if message.from_user.id in config.allowed_user_ids:
            # Log a success message
            bot_logger.info(
                self.bot_msg_tpl.ACCESS_SUCCESS.format(
                    message.from_user.username,
                    message.from_user.id,
                )
            )
        else:
            # Send a typing action to indicate that the bot is processing
            bot.send_chat_action(message.chat.id, 'typing')

            # Log an error message
            bot_logger.error(
                self.bot_msg_tpl.ERROR_ACCESS_LOG_TEMPLATE.format(
                    message.from_user.username,
                    message.from_user.id,
                    message.from_user.language_code,
                    message.from_user.is_bot
                )
            )

            # Send a message to the user indicating that they are blocked
            bot.send_message(
                message.chat.id,
                self.bot_msg_tpl.ERROR_USER_BLOCKED_TEMPLATE
            )

            # Return a CancelUpdate object to stop further processing of the message
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
