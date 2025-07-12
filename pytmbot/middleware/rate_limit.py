#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

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
    WARNING_MESSAGE: Final[str] = (
        "⚠️ You're sending messages too quickly. 🕒 Please slow down."
    )

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

        # Track rate limit violations for logging optimization
        self._violation_count: defaultdict[UserID, int] = defaultdict(int)
        self._last_violation_log: defaultdict[UserID, datetime] = defaultdict(
            lambda: datetime.min
        )

        # Initialize logging only once
        self._initialized = False
        if not self._initialized:
            logger.debug(
                "Rate limit middleware initialized",
                extra={
                    "limit": self.limit,
                    "period": str(self.period),
                },
            )
        self._initialized = True

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
                # Also clean up violation tracking for inactive users
                with suppress(KeyError):
                    del self._violation_count[user_id]
                    del self._last_violation_log[user_id]

    def _is_rate_limited(self, user_id: UserID, current_time: datetime) -> bool:
        """Check if user has exceeded their rate limit."""
        self._clean_old_requests(user_id, current_time)
        return len(self._user_requests[user_id]) >= self.limit

    def _should_log_violation(self, user_id: UserID, current_time: datetime) -> bool:
        """
        Determine if rate limit violation should be logged to avoid spam.

        Logs violations with exponential backoff:
        - First violation: immediately
        - Subsequent violations: with increasing intervals
        """
        violation_count = self._violation_count[user_id]
        last_log_time = self._last_violation_log[user_id]

        # Always log first violation
        if violation_count == 0:
            return True

        # Calculate backoff interval (exponential: 1min, 5min, 15min, 30min, 1hour)
        backoff_intervals = [
            timedelta(minutes=1),
            timedelta(minutes=5),
            timedelta(minutes=15),
            timedelta(minutes=30),
            timedelta(hours=1),
        ]

        interval_index = min(violation_count - 1, len(backoff_intervals) - 1)
        backoff_interval = backoff_intervals[interval_index]

        return current_time - last_log_time >= backoff_interval

    def _handle_rate_limit(self, message: Message, user: User) -> CancelUpdate:
        """Handle rate limit exceeded scenario with optimized logging."""
        current_time = datetime.now()
        user_id = user.id

        # Update violation tracking
        self._violation_count[user_id] += 1

        # Log violation only if necessary (to avoid log spam)
        if self._should_log_violation(user_id, current_time):
            self._last_violation_log[user_id] = current_time

            # Log with contextual information
            logger.warning(
                "Rate limit exceeded",
                extra={
                    "user_id": user_id,
                    "username": user.username or "unknown",
                    "violation_count": self._violation_count[user_id],
                    "limit": self.limit,
                    "period": str(self.period),
                    "chat_id": message.chat.id,
                },
            )

        # Send warning message to user (with error suppression)
        with suppress(Exception):
            self.bot.send_message(chat_id=message.chat.id, text=self.WARNING_MESSAGE)

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
            # Log missing user info only in debug mode or as a one-time error
            logger.error(
                "Missing user information in message",
                extra={"message_id": message.message_id, "chat_id": message.chat.id},
            )
            return CancelUpdate()

        current_time = datetime.now()

        if self._is_rate_limited(user.id, current_time):
            return self._handle_rate_limit(message, user)

        # Track successful request
        self._user_requests[user.id].append(current_time)

        # Reset violation count on successful request
        if user.id in self._violation_count:
            self._violation_count[user.id] = 0

            # Log successful processing only in debug mode
            logger.debug(
                "Request processed successfully",
                extra={
                    "user_id": user.id,
                    "username": user.username or "unknown",
                    "current_requests": len(self._user_requests[user.id]),
                    "limit": self.limit,
                },
            )

        return None

    def post_process(
        self, message: Message, data: Any, exception: Optional[Exception]
    ) -> None:
        """Post-process message after main middleware execution."""
        # Log exceptions only if they occur
        if exception:
            logger.error(
                "Exception in rate limit post-process",
                extra={
                    "exception_type": type(exception).__name__,
                    "exception_message": str(exception),
                    "user_id": message.from_user.id if message.from_user else None,
                },
            )

    def get_stats(self) -> dict[str, Any]:
        """
        Get rate limiting statistics for monitoring.

        Returns:
            Dictionary with current statistics
        """
        current_time = datetime.now()
        active_users = len(self._user_requests)
        total_violations = sum(self._violation_count.values())

        stats = {
            "active_users": active_users,
            "total_violations": total_violations,
            "limit": self.limit,
            "period_seconds": self.period.total_seconds(),
            "timestamp": current_time.isoformat(),
        }

        logger.debug("Rate limit metrics stats", extra=stats)

        return stats
