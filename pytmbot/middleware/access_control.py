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
            context={"component": "middleware"},
        )

    def pre_process(self, message: Message, data: Any) -> Optional[CancelUpdate]:
        user = message.from_user
        if not user:
            logger.error(
                "Message without user info",
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

        base_context = {
            "message_id": message.message_id,
            "chat_id": chat_id,
            "user_id": user_id,
            "username": username,
            "component": "middleware",
        }

        if self._should_block_request(user_id):
            logger.warning(
                "Access blocked",
                context={
                    **base_context,
                    "block_expires": self._blocked_until[user_id].isoformat(),
                },
            )
            return CancelUpdate()

        if user_id not in self.allowed_user_ids:
            return self._handle_unauthorized_access(user_id, username, chat_id)

        logger.debug(
            "Access granted",
            context=base_context,
        )
        return None

    def _should_block_request(self, user_id: int) -> bool:
        return datetime.now() < self._blocked_until[user_id]

    def _handle_unauthorized_access(
        self, user_id: int, username: str, chat_id: int
    ) -> CancelUpdate:
        self._attempt_count[user_id] += 1
        current_attempt = self._attempt_count[user_id]

        base_context = {
            "user_id": user_id,
            "username": username,
            "chat_id": chat_id,
            "attempt_number": current_attempt,
            "component": "middleware",
        }

        if current_attempt >= self.MAX_ATTEMPTS:
            block_until = datetime.now() + timedelta(seconds=self.BLOCK_DURATION)
            self._blocked_until[user_id] = block_until

            logger.warning(
                "User blocked after max attempts",
                context={
                    **base_context,
                    "block_until": block_until.isoformat(),
                },
            )
        else:
            logger.warning(
                "Unauthorized access attempt",
                context={
                    **base_context,
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
                msg += f"⛔ User blocked until `{block_until}`\n"
            else:
                remaining = self.MAX_ATTEMPTS - attempt
                msg += f"❗ Remaining attempts: `{remaining}`\n"

            msg += (
                "\nℹ️ *Informational alert* - access denied.\n"
                "🔍 Verify bot token if unexpected.\n"
                "🛡️ Consider token regeneration if compromised."
            )

            self.bot.send_message(
                chat_id=int(settings.chat_id.global_chat_id[0]),
                text=msg,
                parse_mode="Markdown",
            )
        except Exception as e:
            logger.error(
                "Admin notification failed",
                context={
                    "component": "middleware",
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
                        "Expired blocks cleaned",
                        context={
                            "component": "middleware",
                            "expired_count": len(expired),
                        },
                    )
            except Exception as e:
                logger.error(
                    "Cleanup failed",
                    context={
                        "component": "middleware",
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

        context = {
            "message_id": message.message_id,
            "chat_id": message.chat.id,
            "component": "middleware",
            "error": str(exception),
        }

        if message.from_user:
            context.update(
                {
                    "user_id": message.from_user.id,
                    "username": message.from_user.username or "unknown",
                }
            )

        logger.error("Message processing failed", context=context)
