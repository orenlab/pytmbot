from collections import defaultdict
from typing import Any, Optional, List

from telebot import TeleBot
from telebot.handler_backends import BaseMiddleware, CancelUpdate
from telebot.types import Message

from pytmbot.globals import settings
from pytmbot.logs import bot_logger


class AccessControl(BaseMiddleware):
    """
    Custom middleware class that checks if the user is allowed to access the bot.
    """

    def __init__(self, bot: TeleBot) -> None:
        """
        Initialize the middleware.

        Args:
            bot (TeleBot): The bot object.
        """
        super().__init__()
        self.bot = bot
        self.update_types: List[str] = ["message"]
        self.allowed_user_ids = set(settings.access_control.allowed_user_ids)
        self.attempt_count = defaultdict(int)

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
        user = message.from_user
        if not user:
            bot_logger.error("User information missing in the message.")
            return CancelUpdate()

        user_id = user.id
        user_name = user.username or "unknown"
        chat_id = message.chat.id

        if user_id not in self.allowed_user_ids:
            self.attempt_count[user_id] += 1

            if self.attempt_count[user_id] >= 3:
                bot_logger.log(
                    "BLOCKED",
                    f"User {user_name} (ID: {user_id}) exceeded access attempts. Session blocked.",
                )
                return CancelUpdate()

            bot_logger.log(
                "DENIED",
                f"Access denied for user {user_name} (ID: {user_id}). Unauthorized access attempt.",
            )
            blocked_message = self.__get_message_text(self.attempt_count[user_id])
            self.bot.send_message(chat_id=chat_id, text=blocked_message)

            return CancelUpdate()

        bot_logger.success(f"Access granted for user {user_name} (ID: {user_id}).")
        return None

    def post_process(
            self, message: Message, data: Any, exception: Optional[Exception]
    ) -> None:
        # Implement if necessary or remove if not used.
        pass

    @staticmethod
    def __get_message_text(count: int) -> str:
        """
        Get the appropriate message based on the count.

        Args:
            count (int): The count of attempts.

        Returns:
            str: The appropriate message.
        """
        messages = [
            "⛔🚫🚧 You do not have permission to access this service. I apologize!",
            "🙅‍ Sorry to repeat myself, but you still don't have access to this service. "
            "I apologize for any inconvenience, but I cannot change the access settings. "
            "This is a security issue 🔥🔥🔥. Goodbye! 👋👋👋",
        ]
        return (
            messages[count - 1]
            if 1 <= count <= len(messages)
            else "Access denied. Please contact support."
        )
