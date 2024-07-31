#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from typing import Any, Optional, List

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


class AccessControl(BaseMiddleware, PyTMBotInstance):
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
        super().__init__()
        # Set the bot instance
        self.bot = self.get_bot_instance()
        # Set update types
        self.update_types: List[str] = ['message']
        # Set allowed user IDs
        self.allowed_user_ids = set(config.allowed_user_ids)
        # Initialize the attempt count dictionary
        self.attempt_count = {}

    @bot_logger.catch()
    def pre_process(self, message: Message, data: Any) -> Optional[CancelUpdate]:
        """
        Check if the user is allowed to access the bot.

        Args:
            message (Message): Object from Telebot containing user information.
            data (Any): Additional data from Telebot.

        Returns:
            Optional[CancelUpdate]: An instance of the CancelUpdate class if the user is not allowed to access the bot,
            or None otherwise.
        """
        # Extract user information from the message object
        user = message.from_user
        user_id = user.id
        user_name = user.username
        chat_id = message.chat.id
        language_code = user.language_code
        is_bot = user.is_bot

        # Check if the user ID is in the list of allowed user IDs
        if user_id not in self.allowed_user_ids:
            # Increment the attempt count for the user ID
            self.attempt_count[user_id] = self.attempt_count.get(user_id, 0) + 1

            # Check if the attempt count exceeds the allowed limit
            if self.attempt_count[user_id] >= 3:
                # Log an error message and terminate the session
                error_message = (
                    f"The number of attempts to access the bot has been exceeded. "
                    f"Session for user {user_name} (ID: {user_id}) will be ignored."
                )
                bot_logger.error(error_message)
                return CancelUpdate()

            # Log an error message and send a blocked message to the user
            error_message = (
                f"Access denied for user {user_name} (ID: {user_id}, "
                f"Language: {language_code}, IsBot: {is_bot}). Reason: User is not allowed to access the bot."
            )
            bot_logger.error(error_message)

            blocked_message = self.__get_message_text(self.attempt_count[user_id])

            self.bot.send_message(chat_id, blocked_message)

            return CancelUpdate()

        # Log an info message if the user ID is in the list of allowed user IDs
        bot_logger.info(f"Access granted for user {user_name} (ID: {user_id})")
        return None

    def post_process(self, message: Message, data: Any, exception: Optional[Exception]) -> None:
        """
        Post-process function that handles the message after it has been processed.

        This function takes in the message received from Telebot, additional data, and any exceptions that occurred
        during processing. It handles the message after it has been processed.

        Args:
            message (telebot.types.Message): The message object received from Telebot.
            data (Any): Additional data from Telebot.
            exception (Optional[Exception]): The exception that occurred during processing, if any.
        """

    @staticmethod
    def __get_message_text(count: int) -> str:
        """
        Get the appropriate message based on the count.

        Args:
            count (int): The count of attempts.

        Returns:
            str: The appropriate message.

        """
        # Define the messages to be returned based on the count
        messages = [
            "⛔🚫🚧 You do not have permission to access this service. I apologize!",
            "🙅‍ Sorry to repeat myself, but you still don't have access to this service. "
            "I apologize for any inconvenience, but I cannot change the access settings. "
            "This is a security issue 🔥🔥🔥. Goodbye! 👋👋👋"
        ]

        # Return the message at the index specified by the count
        return messages[count - 1]
