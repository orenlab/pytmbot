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
from pytmbot.logs import BaseComponent
from pytmbot.utils import mask_user_id, mask_username


class AccessControl(BaseMiddleware, BaseComponent):
    """
    Middleware for bot access control with unauthorized access logging,
    temporary blocking, and admin notification.
    """

    MAX_ATTEMPTS: Final[int] = 3
    BLOCK_DURATION: Final[int] = 3600  # seconds
    CLEANUP_INTERVAL: Final[int] = 3600  # seconds
    ADMIN_NOTIFY_SUPPRESSION: Final[int] = 300  # seconds

    def __init__(self, bot: TeleBot) -> None:
        BaseMiddleware.__init__(self)
        BaseComponent.__init__(self)
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

        context = {
            "operation": "initialization",
            "max_attempts": self.MAX_ATTEMPTS,
            "block_duration": self.BLOCK_DURATION,
            "cleanup_interval": self.CLEANUP_INTERVAL,
            "allowed_users_count": len(self.allowed_user_ids),
            "thread_name": "access_control_cleanup"
        }

        with self.log_context(**context) as logger:
            logger.info("AccessControl middleware initialized")

    def pre_process(self, message: Message, data: Any) -> Optional[CancelUpdate]:
        user = message.from_user
        if not user:
            context = {
                "operation": "pre_process",
                "error_type": "missing_user_info",
                "message_id": message.message_id,
                "chat_id": message.chat.id,
                "chat_type": message.chat.type
            }

            with self.log_context(**context) as logger:
                logger.error("Message without user info")
            return CancelUpdate()

        user_id = user.id
        username = user.username or "unknown"
        chat_id = message.chat.id

        base_context = {
            "operation": "pre_process",
            "message_id": message.message_id,
            "chat_id": chat_id,
            "chat_type": message.chat.type,
            "user_id": mask_user_id(user_id),
            "username": mask_username(username),
            "user_is_bot": user.is_bot
        }

        if self._should_block_request(user_id):
            context = {
                **base_context,
                "operation": "access_blocked",
                "block_expires": self._blocked_until[user_id].isoformat(),
                "block_reason": "max_attempts_exceeded"
            }

            with self.log_context(**context) as logger:
                logger.warning("Access blocked")
            return CancelUpdate()

        if user_id not in self.allowed_user_ids:
            return self._handle_unauthorized_access(user_id, username, chat_id, base_context)

        context = {
            **base_context,
            "operation": "access_granted",
            "access_status": "authorized"
        }

        with self.log_context(**context) as logger:
            logger.debug("Access granted")
        return None

    def _should_block_request(self, user_id: int) -> bool:
        return datetime.now() < self._blocked_until[user_id]

    def _handle_unauthorized_access(
            self, user_id: int, username: str, chat_id: int, base_context: dict
    ) -> CancelUpdate:
        self._attempt_count[user_id] += 1
        current_attempt = self._attempt_count[user_id]

        context = {
            **base_context,
            "operation": "unauthorized_access",
            "attempt_number": current_attempt,
            "max_attempts": self.MAX_ATTEMPTS,
            "attempts_remaining": self.MAX_ATTEMPTS - current_attempt,
            "access_status": "denied"
        }

        if current_attempt >= self.MAX_ATTEMPTS:
            block_until = datetime.now() + timedelta(seconds=self.BLOCK_DURATION)
            self._blocked_until[user_id] = block_until

            context.update({
                "operation": "user_blocked",
                "block_until": block_until.isoformat(),
                "block_duration": self.BLOCK_DURATION,
                "block_reason": "max_attempts_exceeded"
            })

            with self.log_context(**context) as logger:
                logger.warning("User blocked after max attempts")
        else:
            with self.log_context(**context) as logger:
                logger.warning("Unauthorized access attempt")

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
            context = {
                "component": "access_control",
                "operation": "admin_notification",
                "user_id": user_id,
                "username": username,
                "chat_id": chat_id,
                "attempt_number": attempt,
                "notification_status": "suppressed",
                "suppression_duration": self.ADMIN_NOTIFY_SUPPRESSION,
                "time_since_last_notify": (now - last_notified).total_seconds()
            }

            with self.log_context(**context) as logger:
                logger.debug("Admin notification suppressed")
            return

        self._last_admin_notify[user_id] = now

        masked_username = mask_username(username)
        masked_user_id = mask_user_id(user_id)

        context = {
            "operation": "admin_notification",
            "user_id": user_id,
            "username": username,
            "masked_username": masked_username,
            "masked_user_id": masked_user_id,
            "chat_id": chat_id,
            "attempt_number": attempt,
            "notification_status": "sending",
            "admin_chat_id": settings.chat_id.global_chat_id[0]
        }

        try:
            msg = (
                f"⚠️ Unauthorized access attempt #{attempt}\n"
                f"👤 User: `{masked_username}` (ID: `{masked_user_id}`)\n"
                f"💬 Chat ID: `{chat_id}`\n"
            )

            if self._should_block_request(user_id):
                block_until = self._blocked_until[user_id].strftime("%Y-%m-%d %H:%M:%S")
                msg += f"⛔ User blocked until `{block_until}`\n"
                context["user_blocked"] = True
                context["block_until"] = block_until
            else:
                remaining = self.MAX_ATTEMPTS - attempt
                msg += f"❗ Remaining attempts: `{remaining}`\n"
                context["user_blocked"] = False
                context["attempts_remaining"] = remaining

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

            context["notification_status"] = "sent"
            context["message_length"] = len(msg)

            with self.log_context(**context) as logger:
                logger.info("Admin notification sent")

        except Exception as e:
            context.update({
                "notification_status": "failed",
                "error": str(e),
                "error_type": type(e).__name__
            })

            with self.log_context(**context) as logger:
                logger.error("Admin notification failed")

    def _periodic_cleanup(self) -> None:
        """Clean expired blocks and reset counters."""
        # Ensure logging is available in thread context
        if not hasattr(self, '_log') or self._log is None:
            import logging
            logging.warning("AccessControl: _log not available in cleanup thread, skipping detailed logging")

        context = {
            "operation": "periodic_cleanup",
            "cleanup_interval": self.CLEANUP_INTERVAL,
            "thread_name": threading.current_thread().name
        }

        try:
            with self.log_context(**context) as logger:
                logger.info("Periodic cleanup started")
        except AttributeError:
            # Fallback to basic logging if context logging fails
            import logging
            logging.info("AccessControl: Periodic cleanup started")

        while True:
            try:
                time.sleep(self.CLEANUP_INTERVAL)
                now = datetime.now()

                expired = [
                    user_id
                    for user_id, until in self._blocked_until.items()
                    if now >= until
                ]

                cleanup_context = {
                    **context,
                    "operation": "cleanup_execution",
                    "cleanup_timestamp": now.isoformat(),
                    "total_blocked_users": len(self._blocked_until),
                    "expired_count": len(expired),
                    "active_blocks": len(self._blocked_until) - len(expired)
                }

                for user_id in expired:
                    del self._blocked_until[user_id]
                    self._attempt_count[user_id] = 0
                    self._last_admin_notify.pop(user_id, None)

                if expired:
                    cleanup_context["expired_user_ids"] = expired
                    try:
                        with self.log_context(**cleanup_context) as logger:
                            logger.info("Expired blocks cleaned")
                    except AttributeError:
                        import logging
                        logging.info(f"AccessControl: Expired blocks cleaned, count: {len(expired)}")
                else:
                    try:
                        with self.log_context(**cleanup_context) as logger:
                            logger.debug("No expired blocks to clean")
                    except AttributeError:
                        import logging
                        logging.debug("AccessControl: No expired blocks to clean")

            except Exception as e:
                error_context = {
                    **context,
                    "operation": "cleanup_error",
                    "error": str(e),
                    "error_type": type(e).__name__
                }

                try:
                    with self.log_context(**error_context) as logger:
                        logger.error("Cleanup failed")
                except AttributeError:
                    import logging
                    logging.error(f"AccessControl: Cleanup failed: {e}")

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
            "operation": "post_process",
            "message_id": message.message_id,
            "chat_id": message.chat.id,
            "chat_type": message.chat.type,
            "error": str(exception),
            "error_type": type(exception).__name__,
            "has_data": bool(data),
            "data_keys": list(data.keys()) if data else []
        }

        if message.from_user:
            context.update({
                "user_id": mask_user_id(message.from_user.id),
                "username": mask_username(message.from_user.username) or "unknown",
                "user_is_bot": message.from_user.is_bot
            })

        with self.log_context(**context) as logger:
            logger.error("Message processing failed")
