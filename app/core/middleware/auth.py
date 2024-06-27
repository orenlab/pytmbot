#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from typing import Any, Optional, List, Type

from telebot.handler_backends import (
    BaseMiddleware,
    CancelUpdate
)
from telebot.types import Message

from app import (
    config,
    PyTMBotInstance
)
from app.core.logs import bot_logger
from app.core.settings.loggers import MessageTpl


class AllowedUser(BaseMiddleware, PyTMBotInstance):
    """
    Custom middleware class that checks if the user is allowed to access the bot.
    """

    def __init__(self) -> None:
        """
        Initialize the middleware.

        This method initializes the middleware by calling the parent class's __init__ method,
        setting the bot message template, and defining the update types.

        Args:
            self (AllowedUser): The instance of the AllowedUser class.

        Returns:
            None
        """
        # Call the parent class's __init__ method
        super().__init__()

        # Initialize the bot instance
        self.bot = self.get_bot_instance()

        # Set the bot message template
        self.bot_msg_tpl: 'Type[MessageTpl]' = MessageTpl

        # Define the update types as ['message', 'inline_query']
        self.update_types: List[str] = ['message', 'inline_query']

    def pre_process(self, message: Message, data: Any) -> CancelUpdate:
        """
        Check if the user is allowed to access the bot.

        Args:
            message (telebot.types.Message): Object from Telebot containing user information.
            data (Any): Additional data from Telebot.

        Returns:
            telebot.types.CancelUpdate: An instance of the CancelUpdate class.
        """

        # Extract user information from the message
        user_id = message.from_user.id  # get user id
        user_name = message.from_user.username  # get username
        chat_id = message.chat.id  # get chat id
        language_code = message.from_user.language_code  # get user language code
        is_bot = message.from_user.is_bot  # get if user is a bot

        # Check if the user is in the list of allowed user IDs
        if user_id not in config.allowed_user_ids:
            # Send a typing action to indicate that the bot is processing
            self.bot.send_chat_action(chat_id, 'typing')

            # Log the failed access
            error_message = (
                f"Failed access for user {user_name} (ID: {user_id}, "
                f"Language: {language_code}, IsBot: {is_bot})"
            )
            bot_logger.error(error_message)

            # Send a message to the user indicating that they are blocked
            blocked_message = self.bot_msg_tpl.ERROR_USER_BLOCKED_TEMPLATE
            self.bot.send_message(chat_id, blocked_message)

            # Cancel any further processing of the message
            return CancelUpdate()

        # Log the successful access
        bot_logger.info(
            f"Successful access for user {user_name} (ID: {user_id})"
        )

    def post_process(self, message: Message, data: Any, exception: Optional[Exception]) -> None:
        """
        Post-process function that handles the message after it has been processed.

        This function takes in the message received from Telebot, additional data, and any exceptions that occurred
        during processing. It handles the message after it has been processed.

        Args:
            message (telebot.types.Message): The message object received from Telebot.
            data (Any): Additional data from Telebot.
            exception (Optional[Exception]): The exception that occurred during processing, if any.

        Returns:
            None
        """
