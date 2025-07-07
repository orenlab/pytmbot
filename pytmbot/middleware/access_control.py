#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Final, Optional, Any

from telebot import TeleBot
from telebot.handler_backends import BaseMiddleware, CancelUpdate
from telebot.types import Message

from pytmbot.globals import settings
from pytmbot.logs import Logger
from pytmbot.utils import mask_user_id, mask_username

logger = Logger()


class AccessControl(BaseMiddleware):
    """
    Middleware for bot access control with unauthorized access logging,
    temporary blocking, and admin notification.
    """

    MAX_ATTEMPTS: Final[int] = 3
    BLOCK_DURATION: Final[int] = 3600  # seconds
    CLEANUP_INTERVAL: Final[int] = 3600  # seconds
    ADMIN_NOTIFY_SUPPRESSION: Final[int] = 300  # seconds

    def __init__(self, bot: TeleBot) -> None:
        super().__init__()
        self.bot = bot
        self.update_types = ["message"]

        self.allowed_user_ids = frozenset(settings.access_control.allowed_user_ids)

        self._attempt_count: defaultdict[int, int] = defaultdict(int)
        self._blocked_until: defaultdict[int, datetime] = defaultdict(
            lambda: datetime.min
        )
        self._last_admin_notify: dict[int, datetime] = {}

        threading.Thread(
            target=self._periodic_cleanup,
            daemon=True,
            name="access_control_cleanup",
        ).start()

        logger.info(
            "AccessControl middleware initialized",
            context={"component": "middleware", "action": "init"},
        )

    def pre_process(self, message: Message, data: Any) -> Optional[CancelUpdate]:
        user = message.from_user
        if not user:
            logger.error(
                "Message received without user info",
                context={
                    "message_id": message.message_id,
                    "chat_id": message.chat.id,
                    "component": "middleware",
                },
            )
            return CancelUpdate()

        user_id = user.id
        username = user.username or "unknown"
        chat_id = message.chat.id

        log_extra = {
            "message_id": message.message_id,
            "chat_id": chat_id,
            "user_id": user_id,
            "username": username,
            "component": "middleware",
        }

        if self._should_block_request(user_id):
            block_time = self._blocked_until[user_id]
            logger.warning(
                f"Blocked access from user {user_id}",
                context={
                    **log_extra,
                    "block_expires": block_time.isoformat(),
                    "action": "block_check",
                },
            )
            return CancelUpdate()

        if user_id not in self.allowed_user_ids:
            return self._handle_unauthorized_access(user_id, username, chat_id)

        logger.debug(
            f"Access granted to user {user_id}",
            context={**log_extra, "action": "access_granted"},
        )
        return None

    def _should_block_request(self, user_id: int) -> bool:
        return datetime.now() < self._blocked_until[user_id]

    def _handle_unauthorized_access(
        self, user_id: int, username: str, chat_id: int
    ) -> CancelUpdate:
        self._attempt_count[user_id] += 1
        current_attempt = self._attempt_count[user_id]

        log_extra = {
            "user_id": user_id,
            "username": username,
            "chat_id": chat_id,
            "attempt_number": current_attempt,
            "component": "middleware",
            "action": "unauthorized_access",
        }

        if current_attempt >= self.MAX_ATTEMPTS:
            block_until = datetime.now() + timedelta(seconds=self.BLOCK_DURATION)
            self._blocked_until[user_id] = block_until

            logger.warning(
                f"User {username} blocked after {current_attempt} failed attempts",
                context={**log_extra, "block_until": block_until.isoformat()},
            )
        else:
            logger.warning(
                f"Unauthorized access attempt #{current_attempt} from {username}",
                context={
                    **log_extra,
                    "attempts_remaining": self.MAX_ATTEMPTS - current_attempt,
                },
            )

        self._notify_admin(user_id, username, chat_id, current_attempt)

        message = self._get_message_text(current_attempt)
        self.bot.send_message(chat_id=chat_id, text=message)
        return CancelUpdate()

    def _notify_admin(
        self, user_id: int, username: str, chat_id: int, attempt: int
    ) -> None:
        now = datetime.now()
        last_notified = self._last_admin_notify.get(user_id, datetime.min)

        if (now - last_notified).total_seconds() < self.ADMIN_NOTIFY_SUPPRESSION:
            return

        self._last_admin_notify[user_id] = now

        masked_username = mask_username(username)
        masked_user_id = mask_user_id(user_id)

        try:
            msg = (
                f"⚠️ Unauthorized access attempt #{attempt}\n"
                f"👤 User: `{masked_username}` (ID: `{masked_user_id}`)\n"
                f"💬 Chat ID: `{chat_id}`\n"
            )

            if self._should_block_request(user_id):
                block_until = self._blocked_until[user_id].strftime("%Y-%m-%d %H:%M:%S")
                msg += f"⛔ User has been *blocked* until `{block_until}`.\n"
            else:
                remaining = self.MAX_ATTEMPTS - attempt
                msg += f"❗ Remaining attempts before block: `{remaining}`\n"

            msg += (
                "\nℹ️ *This is an informational alert.* Access to the bot was *not granted*.\n"
                "🔍 If this was unexpected, please verify your bot token.\n"
                "🛡️ Consider regenerating the token if you suspect a leak."
            )

            self.bot.send_message(
                chat_id=int(settings.chat_id.global_chat_id[0]),
                text=msg,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.exception(
                "Failed to notify admin",
                context={
                    "component": "middleware",
                    "action": "notify_admin",
                    "user_id": user_id,
                    "username": username,
                    "error": str(e),
                },
            )

    def _periodic_cleanup(self) -> None:
        """Clean expired blocks and reset counters."""
        while True:
            try:
                time.sleep(self.CLEANUP_INTERVAL)
                now = datetime.now()

                expired = [
                    user_id
                    for user_id, until in self._blocked_until.items()
                    if now >= until
                ]

                for user_id in expired:
                    del self._blocked_until[user_id]
                    self._attempt_count[user_id] = 0
                    self._last_admin_notify.pop(user_id, None)

                if expired:
                    logger.debug(
                        "Expired blocks cleaned up",
                        context={
                            "component": "middleware",
                            "action": "cleanup",
                            "expired_users": expired,
                        },
                    )
            except Exception as e:
                logger.exception(
                    "Cleanup process failed",
                    context={
                        "component": "middleware",
                        "action": "cleanup_error",
                        "error_type": type(e).__name__,
                        "error": str(e),
                    },
                )

    @staticmethod
    @lru_cache(maxsize=8)
    def _get_message_text(count: int) -> str:
        messages = [
            "⛔🚫🚧 You don't have access to this service.",
            "🙅‍ Sorry, but you still don't have access. "
            "This is a security measure 🔥. Goodbye! 👋",
        ]
        return messages[min(count - 1, len(messages) - 1)]

    def post_process(
        self, message: Message, data: dict[str, Any], exception: Optional[Exception]
    ) -> None:
        if not exception or isinstance(exception, CancelUpdate):
            return

        ctx = {
            "message_id": message.message_id,
            "chat_id": message.chat.id,
            "middleware": "access_control",
            "error_type": type(exception).__name__,
            "error_details": str(exception),
        }

        if message.from_user:
            ctx.update(
                {
                    "user_id": message.from_user.id,
                    "username": message.from_user.username or "unknown",
                }
            )

        logger.error("Error occurred during message processing", **ctx)
