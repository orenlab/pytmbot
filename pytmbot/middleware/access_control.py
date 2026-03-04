#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import threading
from collections import defaultdict
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Final, cast

from telebot import TeleBot
from telebot.handler_backends import BaseMiddleware, CancelUpdate
from telebot.types import CallbackQuery, Message, User

from pytmbot.globals import settings
from pytmbot.logs import BaseComponent
from pytmbot.utils import mask_chat_id, mask_user_id, mask_username


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
    CLEANUP_THREAD_JOIN_TIMEOUT: Final[float] = 2.0

    # Commands that unauthorized users can use within their attempt limit
    SETUP_COMMANDS: Final[set[str]] = {
        "/getmyid",
    }

    def __init__(self, bot: TeleBot) -> None:
        BaseComponent.__init__(self)
        self.bot = bot
        self.update_types = ["message", "callback_query"]

        self.allowed_user_ids = frozenset(settings.access_control.allowed_user_ids)

        self._attempt_count: defaultdict[int, int] = defaultdict(int)
        self._blocked_until: dict[int, datetime] = {}
        self._last_admin_notify: dict[int, datetime] = {}
        self._state_lock = threading.RLock()
        self._cleanup_stop_event = threading.Event()
        self._cleanup_thread = threading.Thread(
            target=self._periodic_cleanup,
            daemon=True,
            name="access_control_cleanup",
        )

        self._cleanup_thread.start()

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
            logger.info("bot.access.control.middleware.init")

    @staticmethod
    def _is_callback_update(update: object) -> bool:
        return isinstance(update, CallbackQuery) or (
            hasattr(update, "data")
            and hasattr(update, "id")
            and hasattr(update, "message")
            and not hasattr(update, "chat")
        )

    def _is_setup_command(self, message_text: str | Message | None) -> bool:
        """Check if the message contains a setup command."""
        raw_text: str | None
        if isinstance(message_text, str):
            raw_text = message_text
        elif message_text is not None and hasattr(message_text, "text"):
            candidate = getattr(message_text, "text", None)
            raw_text = candidate if isinstance(candidate, str) else None
        else:
            raw_text = None

        if not raw_text:
            return False

        # Get the first word/command from the message
        command = raw_text.strip().split()[0].lower()

        # Remove bot username if present (e.g., /getmyid@botname -> /getmyid)
        if "@" in command:
            command = command.split("@")[0]

        return command in self.SETUP_COMMANDS

    @staticmethod
    def _resolve_user_label(user: User | None) -> str:
        """Resolve best-effort user label for logs/alerts."""
        if user is None:
            return "unknown"

        username = getattr(user, "username", None)
        if isinstance(username, str):
            normalized_username = username.strip()
            if normalized_username:
                return normalized_username

        first_name = getattr(user, "first_name", None)
        last_name = getattr(user, "last_name", None)
        name_parts: list[str] = []
        if isinstance(first_name, str) and first_name.strip():
            name_parts.append(first_name.strip())
        if isinstance(last_name, str) and last_name.strip():
            name_parts.append(last_name.strip())

        if name_parts:
            return " ".join(name_parts)

        return "unknown"

    @staticmethod
    def _extract_update_context(
        update: Message | CallbackQuery,
    ) -> tuple[User | None, int | None, str, int | None, str | None]:
        if AccessControl._is_callback_update(update):
            callback_message = getattr(update, "message", None)
            callback_chat = getattr(callback_message, "chat", None)
            chat_id = getattr(callback_chat, "id", None)
            message_id = getattr(callback_message, "message_id", None)
            data = getattr(update, "data", None)
            callback_user = getattr(update, "from_user", None)
            return callback_user, chat_id, "callback_query", message_id, data

        chat = getattr(update, "chat", None)
        chat_id = getattr(chat, "id", None)
        message_id = getattr(update, "message_id", None)
        message_text = getattr(update, "text", None)
        message_user = getattr(update, "from_user", None)
        return message_user, chat_id, "message", message_id, message_text

    def _notify_user_denied(
        self,
        update: Message | CallbackQuery,
        *,
        attempt_count: int,
    ) -> None:
        message_text = self._get_message_text(attempt_count, self.MAX_ATTEMPTS)
        if self._is_callback_update(update):
            callback_update = cast(CallbackQuery, update)
            self.bot.answer_callback_query(
                callback_update.id,
                text=message_text,
                show_alert=True,
            )
            return

        message_chat = getattr(update, "chat", None)
        chat_id = getattr(message_chat, "id", None)
        if isinstance(chat_id, int):
            self.bot.send_message(chat_id=chat_id, text=message_text)

    def pre_process(
        self, update: Message | CallbackQuery, data: object
    ) -> CancelUpdate | None:
        del data
        user, chat_id, update_type, message_id, raw_text = self._extract_update_context(
            update
        )
        if not user:
            context = {
                "operation": "pre_process",
                "error_type": "missing_user_info",
                "message_id": message_id,
                "chat_id": chat_id,
                "chat_type": (
                    getattr(
                        getattr(getattr(update, "message", None), "chat", None),
                        "type",
                        None,
                    )
                    if self._is_callback_update(update)
                    else getattr(getattr(update, "chat", None), "type", "unknown")
                ),
                "update_type": update_type,
            }

            with self.log_context(**context) as logger:
                logger.error("bot.access.without.user.fail")
            return CancelUpdate()

        user_id = user.id
        username = self._resolve_user_label(user)

        if raw_text:
            debug_context = {
                "user_id": mask_user_id(user_id),
                "chat_id": chat_id,
                "text_length": len(raw_text),
                "cmd": raw_text.lstrip().startswith("/"),
                "update_type": update_type,
            }

            with self.log_context(**debug_context) as logger:
                logger.debug("bot.access.incoming.received.debug")

        base_context = {
            "operation": "pre_process",
            "message_id": message_id,
            "chat_id": chat_id,
            "chat_type": (
                getattr(
                    getattr(getattr(update, "message", None), "chat", None),
                    "type",
                    None,
                )
                if self._is_callback_update(update)
                else getattr(getattr(update, "chat", None), "type", "unknown")
            ),
            "user_id": mask_user_id(user_id),
            "username": mask_username(username),
            "user_is_bot": user.is_bot,
            "update_type": update_type,
        }

        # Check if user is currently blocked
        if self._should_block_request(user_id):
            with self._state_lock:
                block_until = self._blocked_until.get(user_id)
            context = {
                **base_context,
                "operation": "access_blocked",
                "block_expires": (
                    block_until.isoformat() if block_until is not None else "unknown"
                ),
                "block_reason": "max_attempts_exceeded",
            }

            with self.log_context(**context) as logger:
                logger.warning("bot.access.blocked.silent.deny")
            if self._is_callback_update(update):
                callback_update = cast(CallbackQuery, update)
                self.bot.answer_callback_query(
                    callback_update.id,
                    text="Access denied.",
                    show_alert=False,
                )
            return CancelUpdate()

        # Authorized users get full access without attempt counting
        if user_id in self.allowed_user_ids:
            context = {
                **base_context,
                "operation": "access_granted",
                "access_status": "authorized",
            }

            with self.log_context(**context) as logger:
                logger.trace("bot.access.granted.authorized.ok")
            return None

        # Unauthorized users: check attempts and handle accordingly
        return self._handle_unauthorized_access(
            user_id=user_id,
            username=username,
            chat_id=chat_id,
            update=update,
            base_context=base_context,
        )

    def _should_block_request(self, user_id: int) -> bool:
        """Check if user should be blocked based on time."""
        with self._state_lock:
            block_until = self._blocked_until.get(user_id)
            if block_until is None:
                return False

            now = datetime.now()
            if now < block_until:
                return True

            # Block has expired between cleanup cycles: clear stale state lazily.
            del self._blocked_until[user_id]
            self._attempt_count[user_id] = 0
            self._last_admin_notify.pop(user_id, None)
            return False

    def _handle_unauthorized_access(
        self,
        user_id: int,
        username: str,
        chat_id: int | None,
        update: Message | CallbackQuery,
        base_context: dict[str, object],
    ) -> CancelUpdate | None:
        """Handle access for unauthorized users with attempt limits."""
        block_until: datetime | None = None
        with self._state_lock:
            self._attempt_count[user_id] += 1
            current_attempt = self._attempt_count[user_id]
            if current_attempt >= self.MAX_ATTEMPTS:
                block_until = datetime.now() + timedelta(seconds=self.BLOCK_DURATION)
                self._blocked_until[user_id] = block_until
        update_text = (
            getattr(update, "text", None)
            if not self._is_callback_update(update)
            else getattr(update, "data", None)
        )
        is_setup_command = (
            not self._is_callback_update(update)
        ) and self._is_setup_command(update_text)

        context = {
            **base_context,
            "operation": "unauthorized_access",
            "attempt_number": current_attempt,
            "max_attempts": self.MAX_ATTEMPTS,
            "attempts_remaining": max(0, self.MAX_ATTEMPTS - current_attempt),
            "access_status": "denied",
            "is_setup_command": is_setup_command,
            "command": (
                update_text.strip().split()[0]
                if isinstance(update_text, str) and update_text.strip()
                else "unknown"
            ),
        }

        # Block user if max attempts reached
        if current_attempt >= self.MAX_ATTEMPTS:
            context.update(
                {
                    "operation": "user_blocked",
                    "block_until": (
                        block_until.isoformat()
                        if block_until is not None
                        else "unknown"
                    ),
                    "block_duration": self.BLOCK_DURATION,
                    "block_reason": "max_attempts_exceeded",
                }
            )

            with self.log_context(**context) as logger:
                logger.warning("bot.access.user.blocked.deny")

            # Silent block - no response to user
            return CancelUpdate()

        # User still has attempts left
        with self.log_context(**context) as logger:
            logger.warning("bot.access.unauthorized.attempt.deny")

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
                logger.info("bot.access.command.allowed.init")

            return None

        # Block non-setup commands
        self._notify_user_denied(update, attempt_count=current_attempt)
        return CancelUpdate()

    def _notify_admin(
        self,
        user_id: int,
        username: str,
        chat_id: int | None,
        attempt: int,
        is_setup_command: bool = False,
    ) -> None:
        """Notify admin about unauthorized access attempts."""
        now = datetime.now()
        time_since_last_notify = 0.0
        with self._state_lock:
            last_notified = self._last_admin_notify.get(user_id, datetime.min)
            time_since_last_notify = (now - last_notified).total_seconds()
            should_suppress = time_since_last_notify < self.ADMIN_NOTIFY_SUPPRESSION
            if not should_suppress:
                self._last_admin_notify[user_id] = now

        if should_suppress:
            context = {
                "operation": "admin_notification",
                "user_id": mask_user_id(user_id),
                "username": mask_username(username),
                "chat_id": chat_id,
                "attempt_number": attempt,
                "notification_status": "suppressed",
                "suppression_duration": self.ADMIN_NOTIFY_SUPPRESSION,
                "time_since_last_notify": time_since_last_notify,
                "is_setup_command": is_setup_command,
            }

            with self.log_context(**context) as logger:
                logger.debug("bot.access.admin.notification.debug")
            return

        masked_username = mask_username(username)
        masked_user_id = mask_user_id(user_id)

        context = {
            "operation": "admin_notification",
            "user_id": masked_user_id,
            "username": masked_username,
            "masked_username": masked_username,
            "masked_user_id": masked_user_id,
            "chat_id": mask_chat_id(chat_id),
            "attempt_number": attempt,
            "notification_status": "sending",
            "admin_chat_id": mask_chat_id(settings.chat_id.global_chat_id[0]),
            "is_setup_command": is_setup_command,
        }

        try:
            # Different message for setup commands vs regular commands
            if is_setup_command:
                msg = (
                    f"ℹ️ Setup command used by unauthorized user (attempt #{attempt})\n"
                    f"👤 User: `{masked_username}` (ID: `{masked_user_id}`)\n"
                    f"💬 Chat ID: `{mask_chat_id(chat_id)}`\n"
                )
            else:
                msg = (
                    f"⚠️ Unauthorized access attempt #{attempt}\n"
                    f"👤 User: `{masked_username}` (ID: `{masked_user_id}`)\n"
                    f"💬 Chat ID: `{mask_chat_id(chat_id)}`\n"
                )

            remaining = max(0, self.MAX_ATTEMPTS - attempt)
            if remaining > 0:
                msg += f"❗ Remaining attempts: `{remaining}`\n"
                context["attempts_remaining"] = remaining
            else:
                msg += "⛔ User will be blocked after this attempt\n"
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
                logger.info("bot.access.admin.notification.info")

        except Exception as e:
            context.update(
                {
                    "notification_status": "failed",
                    "error": str(e),
                    "error_type": type(e).__name__,
                }
            )

            with self.log_context(**context) as logger:
                logger.error("bot.access.admin.notification.fail")

    def _wait_for_cleanup_interval(self) -> bool:
        """Wait for cleanup interval; return True when shutdown was requested."""
        return self._cleanup_stop_event.wait(timeout=self.CLEANUP_INTERVAL)

    def _periodic_cleanup(self) -> None:
        """Clean expired blocks and reset counters."""
        # Ensure logging is available in thread context
        if not hasattr(self, "_log") or self._log is None:
            import logging

            logging.warning("bot.access.control.log.warn")

        context = {
            "operation": "periodic_cleanup",
            "cleanup_interval": self.CLEANUP_INTERVAL,
            "thread_name": threading.current_thread().name,
        }

        try:
            with self.log_context(**context) as logger:
                logger.info("bot.access.periodic.cleanup.start")
        except AttributeError:
            # Fallback to basic logging if context logging fails
            import logging

            logging.info("bot.access.control.periodic.start")

        while not self._cleanup_stop_event.is_set():
            try:
                if self._wait_for_cleanup_interval():
                    break
                now = datetime.now()
                with self._state_lock:
                    expired = [
                        user_id
                        for user_id, until in self._blocked_until.items()
                        if now >= until
                    ]
                    total_blocked_users = len(self._blocked_until)

                    for user_id in expired:
                        del self._blocked_until[user_id]
                        self._attempt_count[user_id] = 0
                        self._last_admin_notify.pop(user_id, None)

                    active_blocks = len(self._blocked_until)

                cleanup_context = {
                    **context,
                    "operation": "cleanup_execution",
                    "cleanup_timestamp": now.isoformat(),
                    "total_blocked_users": total_blocked_users,
                    "expired_count": len(expired),
                    "active_blocks": active_blocks,
                }

                if expired:
                    cleanup_context["expired_user_ids"] = [
                        mask_user_id(user_id) for user_id in sorted(expired)
                    ]
                    try:
                        with self.log_context(**cleanup_context) as logger:
                            logger.info("bot.access.expired.blocks.info")
                    except AttributeError:
                        import logging

                        logging.info("bot.access.control.expired.info")
                else:
                    try:
                        with self.log_context(**cleanup_context) as logger:
                            logger.debug("bot.access.no.expired.debug")
                    except AttributeError:
                        import logging

                        logging.debug("bot.access.control.no.debug")

            except Exception as e:
                error_context = {
                    **context,
                    "operation": "cleanup_error",
                    "error": str(e),
                    "error_type": type(e).__name__,
                }

                try:
                    with self.log_context(**error_context) as logger:
                        logger.error("bot.access.cleanup.fail")
                except AttributeError:
                    import logging

                    logging.error("bot.access.control.cleanup.fail")

    def cleanup(self) -> None:
        """Stop cleanup worker thread."""
        self._cleanup_stop_event.set()
        join = getattr(self._cleanup_thread, "join", None)
        is_alive = getattr(self._cleanup_thread, "is_alive", None)
        if callable(join) and callable(is_alive) and is_alive():
            join(timeout=self.CLEANUP_THREAD_JOIN_TIMEOUT)

    def __del__(self) -> None:
        """Best-effort cleanup on object destruction."""
        try:
            self.cleanup()
        except Exception:
            pass

    @staticmethod
    @lru_cache(maxsize=16)
    def _get_message_text(count: int, max_attempts: int) -> str:
        """Get appropriate message text based on attempt count."""
        messages = [
            (
                "⛔🚫🚧 You don't have access to this service.\n"
                f"💡 You have {max(0, max_attempts - count)} attempts remaining.\n"
                f"🔧 Use `/getmyid` for setup information."
            ),
            (
                "🙅‍ Sorry, but you still don't have access.\n"
                "This is a security measure 🔥.\n"
                f"💡 You have {max(0, max_attempts - count)} attempts remaining.\n"
                f"🔧 Use `/getmyid` for setup information."
            ),
            (
                "🚫 Final warning: Access denied.\n"
                "⛔ You will be blocked after this attempt.\n"
                "💡 Use `/getmyid` for setup information. Goodbye! 👋"
            ),
        ]
        return messages[min(count - 1, len(messages) - 1)]

    def post_process(
        self,
        update: Message | CallbackQuery,
        data: dict[str, object],
        exception: Exception | None,
    ) -> None:
        """Post-process update handling."""
        if not exception or isinstance(exception, CancelUpdate):
            return

        user, chat_id, update_type, message_id, _ = self._extract_update_context(update)
        chat_type = (
            getattr(
                getattr(getattr(update, "message", None), "chat", None), "type", None
            )
            if self._is_callback_update(update)
            else getattr(getattr(update, "chat", None), "type", "unknown")
        )

        context = {
            "operation": "post_process",
            "message_id": message_id,
            "chat_id": chat_id,
            "chat_type": chat_type,
            "update_type": update_type,
            "error": str(exception),
            "error_type": type(exception).__name__,
            "has_data": bool(data),
            "data_keys": list(data.keys()) if data else [],
        }

        if user:
            context.update(
                {
                    "user_id": mask_user_id(user.id),
                    "username": mask_username(self._resolve_user_label(user)),
                    "user_is_bot": user.is_bot,
                }
            )

        with self.log_context(**context) as logger:
            logger.error("bot.access.processing.fail")
