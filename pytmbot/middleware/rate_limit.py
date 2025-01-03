from collections import defaultdict
from contextlib import suppress
from datetime import datetime, timedelta
from typing import Any, Optional, Final, TypeAlias, TypedDict

from telebot import TeleBot
from telebot.handler_backends import BaseMiddleware, CancelUpdate
from telebot.types import Message, User

from pytmbot.logs import Logger

logger = Logger()

# Type aliases for better readability
Timestamp: TypeAlias = datetime
UserID: TypeAlias = int


class RateLimitConfig(TypedDict):
    """Type definition for rate limit configuration."""
    limit: int
    period: timedelta


class RateLimit(BaseMiddleware):
    """
    Middleware for rate limiting user requests to prevent DDoS attacks.

    Uses a sliding window approach to track and limit user requests within
    a specified time period.
    """

    SUPPORTED_UPDATES: Final[list[str]] = ["message"]
    WARNING_MESSAGE: Final[str] = "⚠️ You're sending messages too quickly. 🕒 Please slow down."

    def __init__(self, bot: TeleBot, *, limit: int, period: timedelta) -> None:
        """
        Initialize rate limit middleware.

        Args:
            bot: The bot instance for sending messages
            limit: Maximum number of requests allowed per user within the period
            period: The time period during which requests are counted

        Raises:
            ValueError: If limit or period are invalid
        """
        if limit <= 0:
            raise ValueError("Request limit must be positive")
        if period <= timedelta():
            raise ValueError("Time period must be positive")

        super().__init__()
        self.bot = bot
        self.limit = limit
        self.period = period
        self.update_types = self.SUPPORTED_UPDATES
        self._user_requests: defaultdict[UserID, list[Timestamp]] = defaultdict(list)

    def _clean_old_requests(self, user_id: UserID, current_time: datetime) -> None:
        """Remove expired request timestamps for a user."""
        requests = self._user_requests[user_id]
        cutoff_time = current_time - self.period

        while requests and requests[0] < cutoff_time:
            requests.pop(0)

        # Clean up empty user entries
        if not requests:
            with suppress(KeyError):
                del self._user_requests[user_id]

    def _is_rate_limited(self, user_id: UserID, current_time: datetime) -> bool:
        """Check if user has exceeded their rate limit."""
        self._clean_old_requests(user_id, current_time)
        return len(self._user_requests[user_id]) >= self.limit

    def _handle_rate_limit(self, message: Message, user: User) -> CancelUpdate:
        """Handle rate limit exceeded scenario."""
        logger.warning(
            "Rate limit exceeded",
            extra={
                "user_id": user.id,
                "username": user.username or "unknown",
                "limit": self.limit,
                "period": str(self.period)
            }
        )

        with suppress(Exception):
            self.bot.send_message(
                chat_id=message.chat.id,
                text=self.WARNING_MESSAGE
            )

        return CancelUpdate()

    @logger.catch()
    def pre_process(self, message: Message, data: Any) -> Optional[CancelUpdate]:
        """
        Process incoming message and enforce rate limiting.

        Args:
            message: The incoming message to process
            data: Additional processing data

        Returns:
            CancelUpdate if rate limit exceeded, None otherwise

        Raises:
            CancelUpdate: If user information is missing
        """
        if not (user := message.from_user):
            logger.error("Missing user information in message")
            return CancelUpdate()

        current_time = datetime.now()

        if self._is_rate_limited(user.id, current_time):
            return self._handle_rate_limit(message, user)

        self._user_requests[user.id].append(current_time)
        return None

    def post_process(self, message: Message, data: Any,
                     exception: Optional[Exception]) -> None:
        """Post-process message after main middleware execution."""
        pass  # Currently unused but kept for interface compliance
