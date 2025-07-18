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

from pytmbot.logs import BaseComponent
from pytmbot.utils import mask_user_id, mask_username

# Type aliases for better readability
Timestamp: TypeAlias = datetime
UserID: TypeAlias = int


class RateLimitConfig(TypedDict):
    """Type definition for rate limit configuration."""

    limit: int
    period: timedelta


class RateLimit(BaseMiddleware, BaseComponent):
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

        BaseMiddleware.__init__(self)
        BaseComponent.__init__(self)
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

        context = {
            "operation": "initialization",
            "limit": self.limit,
            "period_seconds": self.period.total_seconds(),
            "period_str": str(self.period),
            "supported_updates": self.SUPPORTED_UPDATES,
            "warning_message": self.WARNING_MESSAGE,
        }

        with self.log_context(**context) as logger:
            logger.info("Rate limit middleware initialized")

    def _clean_old_requests(self, user_id: UserID, current_time: datetime) -> None:
        """Remove expired request timestamps for a user."""
        requests = self._user_requests[user_id]
        cutoff_time = current_time - self.period
        initial_count = len(requests)

        while requests and requests[0] < cutoff_time:
            requests.pop(0)

        cleaned_count = initial_count - len(requests)

        context = {
            "operation": "cleanup_old_requests",
            "user_id": user_id,
            "initial_requests": initial_count,
            "cleaned_requests": cleaned_count,
            "remaining_requests": len(requests),
            "cutoff_time": cutoff_time.isoformat(),
            "current_time": current_time.isoformat(),
        }

        # Clean up empty user entries
        if not requests:
            with suppress(KeyError):
                del self._user_requests[user_id]
                # Also clean up violation tracking for inactive users
                with suppress(KeyError):
                    del self._violation_count[user_id]
                    del self._last_violation_log[user_id]

                context.update({"user_cleaned": True, "violation_data_cleaned": True})

        if cleaned_count > 0:
            with self.log_context(**context) as logger:
                logger.debug("Cleaned old requests for user")

    def _is_rate_limited(self, user_id: UserID, current_time: datetime) -> bool:
        """Check if user has exceeded their rate limit."""
        self._clean_old_requests(user_id, current_time)
        current_requests = len(self._user_requests[user_id])
        is_limited = current_requests >= self.limit

        context = {
            "operation": "rate_limit_check",
            "user_id": user_id,
            "current_requests": current_requests,
            "limit": self.limit,
            "is_rate_limited": is_limited,
            "requests_until_limit": max(0, self.limit - current_requests),
        }

        with self.log_context(**context) as logger:
            logger.debug("Rate limit check completed")

        return is_limited

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
        should_log = current_time - last_log_time >= backoff_interval

        context = {
            "operation": "violation_log_check",
            "user_id": user_id,
            "violation_count": violation_count,
            "last_log_time": last_log_time.isoformat(),
            "current_time": current_time.isoformat(),
            "backoff_interval_seconds": backoff_interval.total_seconds(),
            "time_since_last_log": (current_time - last_log_time).total_seconds(),
            "should_log": should_log,
        }

        with self.log_context(**context) as logger:
            logger.debug("Violation logging check completed")

        return should_log

    def _handle_rate_limit(self, message: Message, user: User) -> CancelUpdate:
        """Handle rate limit exceeded scenario with optimized logging."""
        current_time = datetime.now()
        user_id = user.id

        # Update violation tracking
        self._violation_count[user_id] += 1
        violation_count = self._violation_count[user_id]

        context = {
            "operation": "rate_limit_violation",
            "user_id": user_id,
            "username": user.username or "unknown",
            "user_is_bot": user.is_bot,
            "violation_count": violation_count,
            "limit": self.limit,
            "period_seconds": self.period.total_seconds(),
            "chat_id": message.chat.id,
            "chat_type": message.chat.type,
            "message_id": message.message_id,
            "message_date": message.date,
            "current_time": current_time.isoformat(),
        }

        # Log violation only if necessary (to avoid log spam)
        if self._should_log_violation(user_id, current_time):
            self._last_violation_log[user_id] = current_time
            context.update(
                {
                    "violation_logged": True,
                    "last_violation_log": current_time.isoformat(),
                }
            )

            with self.log_context(**context) as logger:
                logger.warning("Rate limit exceeded")
        else:
            context.update({"violation_logged": False, "log_suppressed": True})

            with self.log_context(**context) as logger:
                logger.debug("Rate limit exceeded (logging suppressed)")

        # Send warning message to user (with error suppression)
        message_sent = False
        try:
            self.bot.send_message(chat_id=message.chat.id, text=self.WARNING_MESSAGE)
            message_sent = True
        except Exception as e:
            message_context = {
                **context,
                "operation": "warning_message_send",
                "message_sent": False,
                "error": str(e),
                "error_type": type(e).__name__,
            }

            with self.log_context(**message_context) as logger:
                logger.error("Failed to send rate limit warning message")

        if message_sent:
            message_context = {
                **context,
                "operation": "warning_message_send",
                "message_sent": True,
                "warning_message": self.WARNING_MESSAGE,
            }

            with self.log_context(**message_context) as logger:
                logger.debug("Rate limit warning message sent")

        return CancelUpdate()

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
            context = {
                "operation": "pre_process",
                "error_type": "missing_user_info",
                "message_id": message.message_id,
                "chat_id": message.chat.id,
                "chat_type": message.chat.type,
                "message_date": message.date,
                "message_content_type": message.content_type,
            }

            with self.log_context(**context) as logger:
                logger.error("Missing user information in message")
            return CancelUpdate()

        current_time = datetime.now()
        user_id = user.id

        base_context = {
            "operation": "pre_process",
            "user_id": user_id,
            "username": user.username or "unknown",
            "user_is_bot": user.is_bot,
            "chat_id": message.chat.id,
            "chat_type": message.chat.type,
            "message_id": message.message_id,
            "message_date": message.date,
            "message_content_type": message.content_type,
            "current_time": current_time.isoformat(),
        }

        if self._is_rate_limited(user_id, current_time):
            context = {
                **base_context,
                "operation": "rate_limit_triggered",
                "rate_limited": True,
            }

            with self.log_context(**context) as logger:
                logger.debug("Rate limit triggered for user")
            return self._handle_rate_limit(message, user)

        # Track successful request
        self._user_requests[user_id].append(current_time)
        current_requests = len(self._user_requests[user_id])

        # Reset violation count on successful request
        violation_reset = False
        if user_id in self._violation_count:
            self._violation_count[user_id] = 0
            violation_reset = True

        context = {
            **base_context,
            "operation": "request_processed",
            "rate_limited": False,
            "current_requests": current_requests,
            "limit": self.limit,
            "violation_count_reset": violation_reset,
            "requests_until_limit": max(0, self.limit - current_requests),
        }

        with self.log_context(**context) as logger:
            logger.debug("Request processed successfully")

        return None

    def post_process(
        self, message: Message, data: Any, exception: Optional[Exception]
    ) -> None:
        """Post-process message after main middleware execution."""
        if not exception:
            return

        context = {
            "operation": "post_process",
            "has_exception": True,
            "exception_type": type(exception).__name__,
            "exception_message": str(exception),
            "message_id": message.message_id,
            "chat_id": message.chat.id,
            "chat_type": message.chat.type,
            "has_data": bool(data),
            "data_keys": list(data.keys()) if data else [],
        }

        if message.from_user:
            context.update(
                {
                    "user_id": mask_user_id(message.from_user.id),
                    "username": mask_username(message.from_user.username) or "unknown",
                    "user_is_bot": message.from_user.is_bot,
                }
            )

        with self.log_context(**context) as logger:
            logger.error("Exception in rate limit post-process")

    def get_stats(self) -> dict[str, Any]:
        """
        Get rate limiting statistics for monitoring.

        Returns:
            Dictionary with current statistics
        """
        current_time = datetime.now()
        active_users = len(self._user_requests)
        total_violations = sum(self._violation_count.values())

        # Calculate additional metrics
        active_violations = sum(
            1 for count in self._violation_count.values() if count > 0
        )
        max_violations = (
            max(self._violation_count.values()) if self._violation_count else 0
        )

        # Calculate current request distribution
        request_counts = [len(requests) for requests in self._user_requests.values()]
        avg_requests = (
            sum(request_counts) / len(request_counts) if request_counts else 0
        )

        stats = {
            "active_users": active_users,
            "total_violations": total_violations,
            "active_violations": active_violations,
            "max_violations_per_user": max_violations,
            "average_requests_per_user": round(avg_requests, 2),
            "limit": self.limit,
            "period_seconds": self.period.total_seconds(),
            "timestamp": current_time.isoformat(),
            "request_distribution": {
                "min": min(request_counts) if request_counts else 0,
                "max": max(request_counts) if request_counts else 0,
                "total": sum(request_counts),
            },
        }

        context = {"operation": "get_stats", **stats}

        with self.log_context(**context) as logger:
            logger.debug("Rate limit statistics generated")

        return stats
