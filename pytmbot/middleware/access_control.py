import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any, Optional, List, Final

from telebot import TeleBot
from telebot.handler_backends import BaseMiddleware, CancelUpdate
from telebot.types import Message

from pytmbot.globals import settings
from pytmbot.logs import Logger

logger = Logger()


class AccessControl(BaseMiddleware):
    """
    Enhanced middleware for bot access control with improved security and performance.
    Designed for synchronous bot implementation.
    """

    # Class-level constants
    MAX_ATTEMPTS: Final[int] = 3
    BLOCK_DURATION: Final[int] = 3600  # seconds
    CLEANUP_INTERVAL: Final[int] = 3600  # cleanup interval in seconds

    def __init__(self, bot: TeleBot) -> None:
        """Initialize the middleware with enhanced tracking and security features."""
        super().__init__()
        self.bot = bot
        self.update_types: List[str] = ["message"]
        self.allowed_user_ids: frozenset = frozenset(settings.access_control.allowed_user_ids)

        # Thread-safe collections
        self._attempt_count = defaultdict(int)
        self._blocked_until = defaultdict(lambda: datetime.min)

        # Start cleanup thread
        cleanup_thread = threading.Thread(
            target=self._periodic_cleanup,
            daemon=True,
            name="access_control_cleanup"
        )
        cleanup_thread.start()

        logger.info(
            f"AccessControl middleware initialized successfully",
            context={"component": "middleware", "action": "init"}
        )

    def pre_process(self, message: Message, data: Any) -> Optional[CancelUpdate]:
        """Process incoming messages with security checks."""
        if not (user := message.from_user):
            logger.error(
                f"Message received without user information",
                context={
                    "message_id": message.message_id,
                    "chat_id": message.chat.id,
                    "component": "middleware"
                }
            )
            return CancelUpdate()

        logger.debug(
            f"Pre-process check for user {user.id}",
            context={
                "allowed_ids": list(self.allowed_user_ids),
                "is_blocked": self._should_block_request(user.id)
            }
        )

        log_extra = {
            "message_id": message.message_id,
            "chat_id": message.chat.id,
            "user_id": user.id,
            "username": user.username or "unknown",
            "component": "middleware"
        }

        if self._should_block_request(user.id):
            block_time = self._blocked_until[user.id]
            logger.warning(
                f"Access blocked: user {user.id} is temporarily restricted",
                context={
                    **log_extra,
                    "block_expires": block_time.isoformat(),
                    "action": "block_check"
                }
            )
            return CancelUpdate()

        if user.id not in self.allowed_user_ids:
            return self._handle_unauthorized_access(user.id, user.username or "unknown", message.chat.id)

        logger.debug(
            f"Access granted to user {user.id}",
            context={**log_extra, "action": "access_granted"}
        )
        return None

    def _should_block_request(self, user_id: int) -> bool:
        """Check if the request should be blocked based on security policies."""
        block_until = self._blocked_until[user_id]
        return datetime.now() < block_until

    def _handle_unauthorized_access(self, user_id: int, username: str, chat_id: int) -> CancelUpdate:
        """Handle unauthorized access attempts with progressive blocking."""
        self._attempt_count[user_id] += 1
        current_attempt = self._attempt_count[user_id]

        log_extra = {
            "user_id": user_id,
            "username": username,
            "chat_id": chat_id,
            "attempt_number": current_attempt,
            "component": "middleware",
            "action": "unauthorized_access"
        }

        if current_attempt >= self.MAX_ATTEMPTS:
            block_until = datetime.now() + timedelta(seconds=self.BLOCK_DURATION)
            self._blocked_until[user_id] = block_until

            logger.warning(
                f"User {username} (ID: {user_id}) blocked after {current_attempt} failed attempts",
                context={
                    **log_extra,
                    "block_duration": self.BLOCK_DURATION,
                    "block_until": block_until.isoformat()
                }
            )
        else:
            logger.warning(
                f"Unauthorized access attempt #{current_attempt} from user {username} (ID: {user_id})",
                context={
                    **log_extra,
                    "attempts_remaining": self.MAX_ATTEMPTS - current_attempt
                }
            )

        message = self._get_message_text(current_attempt)
        self.bot.send_message(chat_id=chat_id, text=message)
        return CancelUpdate()

    def _periodic_cleanup(self) -> None:
        """Periodically clean up expired blocks and attempt counts."""
        while True:
            try:
                time.sleep(self.CLEANUP_INTERVAL)
                now = datetime.now()

                expired_blocks = [
                    user_id for user_id, block_time in self._blocked_until.items()
                    if now >= block_time
                ]

                if expired_blocks:
                    for user_id in expired_blocks:
                        del self._blocked_until[user_id]
                        self._attempt_count[user_id] = 0

                    logger.debug(
                        f"Cleanup completed: removed {len(expired_blocks)} expired blocks",
                        context={
                            "component": "middleware",
                            "action": "cleanup",
                            "expired_count": len(expired_blocks),
                            "expired_users": expired_blocks
                        }
                    )

            except Exception as e:
                logger.exception(
                    f"Cleanup process failed: {str(e)}",
                    context={
                        "component": "middleware",
                        "action": "cleanup_error",
                        "error_type": type(e).__name__
                    }
                )

    @staticmethod
    @lru_cache(maxsize=8)
    def _get_message_text(count: int) -> str:
        """Get cached message text based on attempt count."""
        messages = [
            "⛔🚫🚧 You don't have access to this service.",
            "🙅‍ Sorry, but you still don't have access to this service. "
            "I cannot change access settings. "
            "This is a security measure 🔥. Goodbye! 👋",
        ]
        return messages[min(count - 1, len(messages) - 1)]

    def post_process(self, message: Message, data: dict, exception: Optional[Exception]) -> None:
        """
        Post-process messages and handle any exceptions that occurred.
        """
        if not exception or isinstance(exception, CancelUpdate):
            return

        ctx = {
            "message_id": message.message_id,
            "chat_id": message.chat.id,
            "middleware": "access_control",
            "error_type": type(exception).__name__,
            "error_details": str(exception)
        }

        if message.from_user:
            ctx.update({
                "user_id": message.from_user.id,
                "username": message.from_user.username or "unknown"
            })

        logger.error(
            "Error occurred during message processing",
            **ctx
        )
