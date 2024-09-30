from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Optional, List

from telebot import TeleBot
from telebot.handler_backends import BaseMiddleware, CancelUpdate
from telebot.types import Message

from pytmbot.logs import bot_logger


class RateLimit(BaseMiddleware):
    """
    Middleware for rate limiting user requests to prevent DDoS attacks.

    This middleware keeps track of user requests and limits the number of requests
    each user can make within a specified time period.
    """

    def __init__(self, bot: TeleBot, limit: int, period: timedelta) -> None:
        """
        Initializes the rate limit middleware.

        Args:
            bot (TeleBot): The bot object.
            limit (int): Maximum number of requests allowed per user within the period.
            period (timedelta): The time period during which requests are counted.
        """
        super().__init__()
        self.bot = bot
        self.update_types: List[str] = ["message"]
        self.limit = limit
        self.period = period
        self.user_requests = defaultdict(list)

    @bot_logger.catch()
    def pre_process(self, message: Message, data: Any) -> Optional[CancelUpdate]:
        """
        Processes the incoming message and checks for rate limiting.

        Args:
            message (Message): The incoming message from the user.
            data (Any): Additional data from Telebot.

        Returns:
            Optional[CancelUpdate]: An instance of CancelUpdate if the user exceeds the rate limit,
            or None otherwise.
        """
        user = message.from_user
        if not user:
            bot_logger.error("User information missing in the message.")
            return CancelUpdate()

        user_id = user.id
        now = datetime.now()
        user_requests = self.user_requests[user_id]

        # Remove timestamps older than the defined period
        while user_requests and user_requests[0] < now - self.period:
            user_requests.pop(0)

        # Check if the limit is exceeded
        if len(user_requests) >= self.limit:
            bot_logger.warning(
                f"User {user.username or 'unknown'} (ID: {user_id}) exceeded rate limit."
            )
            self.bot.send_message(
                chat_id=message.chat.id,
                text="You're sending messages too quickly. Please slow down.",
            )
            return CancelUpdate()

        user_requests.append(now)
        return None

    def post_process(
        self, message: Message, data: Any, exception: Optional[Exception]
    ) -> None:
        """
        Post-processes the incoming message.

        This method can be implemented if necessary to handle any post-processing after
        the main logic of the middleware has executed.

        Args:
            message (Message): The message object being processed.
            data (Any): Additional data from Telebot.
            exception (Optional[Exception]): Exception raised during processing, if any.
        """
        # Implement if necessary or remove if not used.
        pass
