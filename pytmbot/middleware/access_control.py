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
from typing import Final, Optional, Any, Set

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

    All users (authorized and unauthorized) are subject to attempt limits.
    Unauthorized users get blocked after MAX_ATTEMPTS, but can still use
    setup commands within their attempt limit.
    """

    MAX_ATTEMPTS: Final[int] = 3
    BLOCK_DURATION: Final[int] = 3600  # seconds
    CLEANUP_INTERVAL: Final[int] = 3600  # seconds
    ADMIN_NOTIFY_SUPPRESSION: Final[int] = 300  # seconds

    # Commands that unauthorized users can use within their attempt limit
    SETUP_COMMANDS: Final[Set[str]] = {
        "/getmyid",
    }

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
            "setup_commands": list(self.SETUP_COMMANDS),
            "thread_name": "access_control_cleanup",
        }

        with self.log_context(**context) as logger:
            logger.info("AccessControl middleware initialized")

    def _is_setup_command(self, message: Message) -> bool:
        """Check if the message contains a setup command."""
        if not message.text:
            return False

        # Get the first word/command from the message
        command = message.text.strip().split()[0].lower()

        # Remove bot username if present (e.g., /getmyid@botname -> /getmyid)
        if "@" in command:
            command = command.split("@")[0]

        return command in self.SETUP_COMMANDS

    def pre_process(self, message: Message, data: Any) -> Optional[CancelUpdate]:
        user = message.from_user
        if not user:
            context = {
                "operation": "pre_process",
                "error_type": "missing_user_info",
                "message_id": message.message_id,
                "chat_id": message.chat.id,
                "chat_type": message.chat.type,
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
            "user_is_bot": user.is_bot,
        }

        # Check if user is currently blocked
        if self._should_block_request(user_id):
            context = {
                **base_context,
                "operation": "access_blocked",
                "block_expires": self._blocked_until[user_id].isoformat(),
                "block_reason": "max_attempts_exceeded",
            }

            with self.log_context(**context) as logger:
                logger.warning("Access blocked - silent cancel")
            return CancelUpdate()

        # Authorized users get full access without attempt counting
        if user_id in self.allowed_user_ids:
            context = {
                **base_context,
                "operation": "access_granted",
                "access_status": "authorized",
            }

            with self.log_context(**context) as logger:
                logger.debug("Access granted to authorized user")
            return None

        # Unauthorized users: check attempts and handle accordingly
        return self._handle_unauthorized_access(
            user_id, username, chat_id, message, base_context
        )

    def _should_block_request(self, user_id: int) -> bool:
        """Check if user should be blocked based on time."""
        return datetime.now() < self._blocked_until[user_id]

    def _handle_unauthorized_access(
        self,
        user_id: int,
        username: str,
        chat_id: int,
        message: Message,
        base_context: dict,
    ) -> Optional[CancelUpdate]:
        """Handle access for unauthorized users with attempt limits."""

        self._attempt_count[user_id] += 1
        current_attempt = self._attempt_count[user_id]
        is_setup_command = self._is_setup_command(message)

        context = {
            **base_context,
            "operation": "unauthorized_access",
            "attempt_number": current_attempt,
            "max_attempts": self.MAX_ATTEMPTS,
            "attempts_remaining": max(0, self.MAX_ATTEMPTS - current_attempt),
            "access_status": "denied",
            "is_setup_command": is_setup_command,
            "command": message.text.strip().split()[0] if message.text else "unknown",
        }

        # Block user if max attempts reached
        if current_attempt >= self.MAX_ATTEMPTS:
            block_until = datetime.now() + timedelta(seconds=self.BLOCK_DURATION)
            self._blocked_until[user_id] = block_until

            context.update(
                {
                    "operation": "user_blocked",
                    "block_until": block_until.isoformat(),
                    "block_duration": self.BLOCK_DURATION,
                    "block_reason": "max_attempts_exceeded",
                }
            )

            with self.log_context(**context) as logger:
                logger.warning("User blocked after max attempts - silent cancel")

            # Silent block - no response to user
            return CancelUpdate()

        # User still has attempts left
        with self.log_context(**context) as logger:
            logger.warning("Unauthorized access attempt")

        # Notify admin about the attempt
        self._notify_admin(
            user_id, username, chat_id, current_attempt, is_setup_command
        )

        # Allow setup commands within attempt limit
        if is_setup_command:
            context.update(
                {
                    "operation": "setup_command_allowed",
                    "access_status": "setup_command_granted",
                }
            )

            with self.log_context(**context) as logger:
                logger.info("Setup command allowed within attempt limit")

            return None

        # Block non-setup commands
        message_text = self._get_message_text(current_attempt)
        self.bot.send_message(chat_id=chat_id, text=message_text)
        return CancelUpdate()

    def _notify_admin(
        self,
        user_id: int,
        username: str,
        chat_id: int,
        attempt: int,
        is_setup_command: bool = False,
    ) -> None:
        """Notify admin about unauthorized access attempts."""
        now = datetime.now()
        last_notified = self._last_admin_notify.get(user_id, datetime.min)

        if (now - last_notified).total_seconds() < self.ADMIN_NOTIFY_SUPPRESSION:
            context = {
                "operation": "admin_notification",
                "user_id": user_id,
                "username": username,
                "chat_id": chat_id,
                "attempt_number": attempt,
                "notification_status": "suppressed",
                "suppression_duration": self.ADMIN_NOTIFY_SUPPRESSION,
                "time_since_last_notify": (now - last_notified).total_seconds(),
                "is_setup_command": is_setup_command,
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
            "admin_chat_id": settings.chat_id.global_chat_id[0],
            "is_setup_command": is_setup_command,
        }

        try:
            # Different message for setup commands vs regular commands
            if is_setup_command:
                msg = (
                    f"ℹ️ Setup command used by unauthorized user (attempt #{attempt})\n"
                    f"👤 User: `{masked_username}` (ID: `{masked_user_id}`)\n"
                    f"💬 Chat ID: `{chat_id}`\n"
                )
            else:
                msg = (
                    f"⚠️ Unauthorized access attempt #{attempt}\n"
                    f"👤 User: `{masked_username}` (ID: `{masked_user_id}`)\n"
                    f"💬 Chat ID: `{chat_id}`\n"
                )

            remaining = max(0, self.MAX_ATTEMPTS - attempt)
            if remaining > 0:
                msg += f"❗ Remaining attempts: `{remaining}`\n"
                context["attempts_remaining"] = remaining
            else:
                msg += f"⛔ User will be blocked after this attempt\n"
                context["user_will_be_blocked"] = True

            if is_setup_command:
                msg += (
                    f"\n💡 This is normal for bot setup.\n"
                    f"🔐 Add user ID to config if access should be granted.\n"
                    f"🔧 Setup commands available: `{', '.join(self.SETUP_COMMANDS)}`"
                )
            else:
                msg += (
                    f"\nℹ️ *Access denied* - not a setup command.\n"
                    f"🔍 Verify bot token if unexpected.\n"
                    f"🛡️ Consider token regeneration if compromised.\n"
                    f"💡 Setup commands: `{', '.join(self.SETUP_COMMANDS)}`"
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
            context.update(
                {
                    "notification_status": "failed",
                    "error": str(e),
                    "error_type": type(e).__name__,
                }
            )

            with self.log_context(**context) as logger:
                logger.error("Admin notification failed")

    def _periodic_cleanup(self) -> None:
        """Clean expired blocks and reset counters."""
        # Ensure logging is available in thread context
        if not hasattr(self, "_log") or self._log is None:
            import logging

            logging.warning(
                "AccessControl: _log not available in cleanup thread, skipping detailed logging"
            )

        context = {
            "operation": "periodic_cleanup",
            "cleanup_interval": self.CLEANUP_INTERVAL,
            "thread_name": threading.current_thread().name,
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
                    "active_blocks": len(self._blocked_until) - len(expired),
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

                        logging.info(
                            f"AccessControl: Expired blocks cleaned, count: {len(expired)}"
                        )
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
                    "error_type": type(e).__name__,
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
        """Get appropriate message text based on attempt count."""
        messages = [
            (
                "⛔🚫🚧 You don't have access to this service.\n"
                f"💡 You have {3 - count} attempts remaining.\n"
                f"🔧 Use `/getmyid` for setup information."
            ),
            (
                "🙅‍ Sorry, but you still don't have access.\n"
                "This is a security measure 🔥.\n"
                f"💡 You have {3 - count} attempts remaining.\n"
                f"🔧 Use `/getmyid` for setup information."
            ),
            (
                "🚫 Final warning: Access denied.\n"
                "⛔ You will be blocked after this attempt.\n"
                f"💡 Use `/getmyid` for setup information. Goodbye! 👋"
            ),
        ]
        return messages[min(count - 1, len(messages) - 1)]

    def post_process(
        self, message: Message, data: dict[str, Any], exception: Optional[Exception]
    ) -> None:
        """Post-process message handling."""
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
            "data_keys": list(data.keys()) if data else [],
        }

        if message.from_user:
            context.update(
                {
                    "user_id": mask_user_id(message.from_user.id),
                    "username": mask_username(message.from_user.username or "unknown"),
                    "user_is_bot": message.from_user.is_bot,
                }
            )

        with self.log_context(**context) as logger:
            logger.error("Message processing failed")
