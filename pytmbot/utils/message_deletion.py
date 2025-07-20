#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import threading
import time
import weakref
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Callable, DefaultDict, Final, TypeAlias

from telebot import TeleBot
from telebot.apihelper import ApiTelegramException

from pytmbot.logs import BaseComponent

# Type aliases for better readability
_UserID: TypeAlias = int
_MessageID: TypeAlias = int
_ChatID: TypeAlias = int
_TaskKey: TypeAlias = tuple[_UserID, _MessageID]


class _DeletionStatus(Enum):
    """Enumeration of possible deletion operation statuses."""

    SUCCESS = auto()
    FAILED = auto()
    LIMIT_EXCEEDED = auto()
    SCHEDULED = auto()
    ALREADY_SCHEDULED = auto()


@dataclass(frozen=True, slots=True)
class _DeletionResult:
    """
    Result of a message deletion scheduling operation.

    Attributes:
        status: The status of the deletion operation
        message_id: ID of the message that was processed
        user_id: ID of the user who requested the deletion
        pending_count: Current number of pending deletions for the user
        error_message: Optional error message if operation failed
    """

    status: _DeletionStatus
    message_id: _MessageID
    user_id: _UserID
    pending_count: int
    error_message: str | None = None

    def __bool__(self) -> bool:
        """Return True if the operation was successful."""
        return self.status in (_DeletionStatus.SUCCESS, _DeletionStatus.SCHEDULED)


@dataclass(slots=True)
class _DeletionTask:
    """
    Internal representation of a scheduled deletion task.

    Attributes:
        bot_ref: Weak reference to the bot instance to prevent memory leaks
        chat_id: Telegram chat ID where the message is located
        message_id: Telegram message ID to be deleted
        user_id: ID of the user who triggered the deletion
        delay_seconds: Delay in seconds before deletion
        created_at: Timestamp when the task was created
        callback: Optional callback function to execute after deletion
    """

    bot_ref: weakref.ReferenceType[TeleBot]
    chat_id: _ChatID
    message_id: _MessageID
    user_id: _UserID
    delay_seconds: int
    created_at: float = field(default_factory=time.time)
    callback: Callable[[_DeletionResult], None] | None = None

    def __post_init__(self) -> None:
        """Validate task parameters after initialization."""
        if self.delay_seconds < 1:
            raise ValueError("delay_seconds must be at least 1")
        if self.delay_seconds > 3600:
            raise ValueError("delay_seconds must not exceed 3600")


class _MessageDeletionManager(BaseComponent):
    """
    Thread-safe singleton manager for scheduling automatic message deletions.

    This class implements a secure mechanism for automatically deleting Telegram
    messages after a specified delay. It includes built-in protection against
    resource exhaustion through per-user limits and uses weak references to
    prevent memory leaks.

    Security Features:
    - Rate limiting per user to prevent DoS attacks
    - Thread-safe operations with proper locking
    - Daemon threads that don't block application shutdown
    - Automatic cleanup of stale references and data

    Thread Safety:
    This class is thread-safe and can be used concurrently from multiple threads.
    All public methods are protected by appropriate locking mechanisms.
    """

    # Class constants
    _DEFAULT_MAX_PENDING_PER_USER: Final[int] = 3
    _DEFAULT_CLEANUP_INTERVAL: Final[int] = 300  # 5 minutes
    _MAX_DELAY_SECONDS: Final[int] = 3600  # 1 hour
    _MIN_DELAY_SECONDS: Final[int] = 1

    _instance: _MessageDeletionManager | None = None
    _instance_lock: threading.Lock = threading.Lock()

    def __new__(cls) -> _MessageDeletionManager:
        """
        Implement thread-safe singleton pattern.

        Returns:
            The singleton instance of _MessageDeletionManager
        """
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """
        Initialize the _MessageDeletionManager instance.

        Note: Due to singleton pattern, this method should only run once.
        """
        # Prevent multiple initialization
        if hasattr(self, "_initialized"):
            return

        # Initialize BaseComponent first
        super().__init__("MessageDeletionManager")

        self._user_pending_deletions: DefaultDict[_UserID, set[_MessageID]] = (
            defaultdict(set)
        )
        self._active_tasks: dict[_TaskKey, _DeletionTask] = {}
        self._deletion_lock: threading.RLock = threading.RLock()
        self._max_pending_per_user: int = self._DEFAULT_MAX_PENDING_PER_USER
        self._stats_lock: threading.Lock = threading.Lock()

        # Statistics tracking
        self._stats: dict[str, int] = {
            "scheduled": 0,
            "completed": 0,
            "failed": 0,
            "limit_exceeded": 0,
            "already_scheduled": 0,
        }

        # Start cleanup daemon
        self._start_cleanup_daemon()
        self._initialized = True

        with self.log_context(action="initialize") as log:
            log.info("MessageDeletionManager initialized successfully")

    def _start_cleanup_daemon(self) -> None:
        """Start the cleanup daemon thread for periodic maintenance."""

        def _cleanup_worker() -> None:
            """Worker function for periodic cleanup of stale data."""
            with self.log_context(action="cleanup_daemon") as log:
                log.debug("Cleanup daemon started")

                while True:
                    try:
                        time.sleep(self._DEFAULT_CLEANUP_INTERVAL)
                        self._cleanup_stale_references()
                    except Exception as e:
                        log.error(f"Cleanup daemon error: {e}")

        cleanup_thread = threading.Thread(
            target=_cleanup_worker, name="MessageDeletionCleanup", daemon=True
        )
        cleanup_thread.start()

    def _cleanup_stale_references(self) -> None:
        """Remove stale weak references and expired tasks."""
        with self._deletion_lock:
            # Clean up tasks with dead weak references
            stale_keys = [
                key
                for key, task in self._active_tasks.items()
                if task.bot_ref() is None
            ]

            cleaned_count = 0
            for key in stale_keys:
                user_id, message_id = key
                self._active_tasks.pop(key, None)
                self._user_pending_deletions[user_id].discard(message_id)
                cleaned_count += 1

            # Clean up empty user entries
            empty_users = [
                user_id
                for user_id, messages in self._user_pending_deletions.items()
                if not messages
            ]
            for user_id in empty_users:
                del self._user_pending_deletions[user_id]

            if cleaned_count > 0 or empty_users:
                with self.log_context(
                        action="cleanup_stale_references",
                        cleaned_tasks=cleaned_count,
                        empty_users_cleaned=len(empty_users)
                ) as log:
                    log.debug(f"Cleaned up {cleaned_count} stale references and {len(empty_users)} empty user entries")

    @contextmanager
    def _update_stats(self, stat_name: str):
        """Context manager for thread-safe statistics updates."""
        try:
            yield
            with self._stats_lock:
                self._stats[stat_name] = self._stats.get(stat_name, 0) + 1
        except Exception:
            with self._stats_lock:
                self._stats["failed"] = self._stats.get("failed", 0) + 1
            raise

    def configure(self, max_pending_per_user: int) -> None:
        """
        Configure the deletion manager parameters.

        Args:
            max_pending_per_user: Maximum number of pending deletions per user

        Raises:
            ValueError: If max_pending_per_user is not positive
        """
        if max_pending_per_user <= 0:
            raise ValueError("max_pending_per_user must be positive")

        with self._deletion_lock:
            old_limit = self._max_pending_per_user
            self._max_pending_per_user = max_pending_per_user

        with self.log_context(
                action="configure",
                old_limit=old_limit,
                new_limit=max_pending_per_user
        ) as log:
            log.info(
                f"MessageDeletionManager configured: max_pending_per_user changed from {old_limit} to {max_pending_per_user}")

    def schedule_deletion(
            self,
            bot: TeleBot,
            chat_id: _ChatID,
            message_id: _MessageID,
            user_id: _UserID,
            delay_seconds: int = 30,
            callback: Callable[[_DeletionResult], None] | None = None,
    ) -> _DeletionResult:
        """
        Schedule a message for automatic deletion after a specified delay.

        Args:
            bot: TeleBot instance used for deletion
            chat_id: Telegram chat ID where the message is located
            message_id: Telegram message ID to delete
            user_id: ID of the user requesting deletion
            delay_seconds: Delay before deletion (1-3600 seconds)
            callback: Optional callback function executed after deletion attempt

        Returns:
            _DeletionResult containing the operation status and details

        Raises:
            ValueError: If delay_seconds is outside valid range
            TypeError: If required parameters are not of expected types
        """
        # Input validation
        if not isinstance(delay_seconds, int) or not (
                self._MIN_DELAY_SECONDS <= delay_seconds <= self._MAX_DELAY_SECONDS
        ):
            raise ValueError(
                f"delay_seconds must be between {self._MIN_DELAY_SECONDS} and {self._MAX_DELAY_SECONDS}"
            )

        if not all(isinstance(x, int) for x in [chat_id, message_id, user_id]):
            raise TypeError("chat_id, message_id, and user_id must be integers")

        with self.log_context(
                action="schedule_deletion",
                user_id=user_id,
                chat_id=chat_id,
                message_id=message_id,
                delay_seconds=delay_seconds
        ) as log:
            with self._deletion_lock:
                current_pending = len(self._user_pending_deletions[user_id])
                task_key = (user_id, message_id)

                # Check if already scheduled
                if task_key in self._active_tasks:
                    with self._update_stats("already_scheduled"):
                        log.warning("Duplicate deletion request - already scheduled")
                        return _DeletionResult(
                            status=_DeletionStatus.ALREADY_SCHEDULED,
                            message_id=message_id,
                            user_id=user_id,
                            pending_count=current_pending,
                            error_message="Deletion already scheduled for this message",
                        )

                # Check if limit is exceeded
                if current_pending >= self._max_pending_per_user:
                    with self._update_stats("limit_exceeded"):
                        log.warning(
                            f"Deletion limit exceeded: {current_pending}/{self._max_pending_per_user}"
                        )
                        return _DeletionResult(
                            status=_DeletionStatus.LIMIT_EXCEEDED,
                            message_id=message_id,
                            user_id=user_id,
                            pending_count=current_pending,
                            error_message="Maximum pending deletions exceeded",
                        )

                # Create and store task
                try:
                    task = _DeletionTask(
                        bot_ref=weakref.ref(bot),
                        chat_id=chat_id,
                        message_id=message_id,
                        user_id=user_id,
                        delay_seconds=delay_seconds,
                        callback=callback,
                    )
                except ValueError as e:
                    log.error(f"Invalid task parameters: {e}")
                    return _DeletionResult(
                        status=_DeletionStatus.FAILED,
                        message_id=message_id,
                        user_id=user_id,
                        pending_count=current_pending,
                        error_message=str(e),
                    )

                self._active_tasks[task_key] = task
                self._user_pending_deletions[user_id].add(message_id)

            # Start deletion thread
            deletion_thread = threading.Thread(
                target=self._execute_deletion,
                args=(task,),
                name=f"MessageDeletion-{user_id}-{message_id}",
                daemon=True,
            )
            deletion_thread.start()

            with self._update_stats("scheduled"):
                log.info(
                    f"Deletion scheduled successfully - pending: {current_pending + 1}/{self._max_pending_per_user}"
                )

                return _DeletionResult(
                    status=_DeletionStatus.SCHEDULED,
                    message_id=message_id,
                    user_id=user_id,
                    pending_count=current_pending + 1,
                )

    def _execute_deletion(self, task: _DeletionTask) -> None:
        """
        Execute the actual message deletion after the specified delay.

        Args:
            task: The deletion task to execute
        """
        task_key = (task.user_id, task.message_id)
        result: _DeletionResult | None = None

        with self.log_context(
                action="execute_deletion",
                user_id=task.user_id,
                chat_id=task.chat_id,
                message_id=task.message_id,
                delay_seconds=task.delay_seconds,
                task_age_seconds=int(time.time() - task.created_at)
        ) as log:
            try:
                log.debug(f"Starting deletion countdown - waiting {task.delay_seconds}s")

                # Wait for the specified delay
                time.sleep(task.delay_seconds)

                # Get bot instance from weak reference
                bot = task.bot_ref()
                if bot is None:
                    raise RuntimeError("Bot instance no longer available")

                # Attempt deletion
                bot.delete_message(task.chat_id, task.message_id)

                with self._update_stats("completed"):
                    result = _DeletionResult(
                        status=_DeletionStatus.SUCCESS,
                        message_id=task.message_id,
                        user_id=task.user_id,
                        pending_count=self.get_pending_count(task.user_id) - 1,
                    )

                    log.success("Message deletion completed successfully")

            except ApiTelegramException as e:
                error_msg = f"Telegram API error during deletion: {e}"
                log.error(error_msg)
                result = _DeletionResult(
                    status=_DeletionStatus.FAILED,
                    message_id=task.message_id,
                    user_id=task.user_id,
                    pending_count=self.get_pending_count(task.user_id) - 1,
                    error_message=error_msg,
                )

            except Exception as e:
                error_msg = f"Unexpected error during deletion: {e}"
                log.error(error_msg)
                result = _DeletionResult(
                    status=_DeletionStatus.FAILED,
                    message_id=task.message_id,
                    user_id=task.user_id,
                    pending_count=self.get_pending_count(task.user_id) - 1,
                    error_message=error_msg,
                )

            finally:
                # Always clean up tracking data
                with self._deletion_lock:
                    self._active_tasks.pop(task_key, None)
                    self._user_pending_deletions[task.user_id].discard(task.message_id)

                log.debug("Task cleanup completed")

                # Execute callback if provided
                if task.callback and result:
                    try:
                        task.callback(result)
                        log.debug("Callback executed successfully")
                    except Exception as e:
                        log.error(f"Error executing deletion callback: {e}")

    def get_pending_count(self, user_id: _UserID) -> int:
        """
        Get the current number of pending deletions for a user.

        Args:
            user_id: ID of the user to check

        Returns:
            Number of pending deletions for the user
        """
        with self._deletion_lock:
            count = len(self._user_pending_deletions[user_id])

        with self.log_context(
                action="get_pending_count",
                user_id=user_id,
                pending_count=count
        ) as log:
            log.debug(f"Retrieved pending count for user: {count}")

        return count

    def cancel_user_deletions(self, user_id: _UserID) -> int:
        """
        Cancel all pending deletions for a specific user.

        Args:
            user_id: ID of the user whose deletions to cancel

        Returns:
            Number of deletions that were cancelled
        """
        with self.log_context(
                action="cancel_user_deletions",
                user_id=user_id
        ) as log:
            with self._deletion_lock:
                message_ids = self._user_pending_deletions[user_id].copy()
                cancelled_count = 0

                for message_id in message_ids:
                    task_key = (user_id, message_id)
                    if task_key in self._active_tasks:
                        self._active_tasks.pop(task_key)
                        cancelled_count += 1

                self._user_pending_deletions[user_id].clear()

            if cancelled_count > 0:
                log.info(f"Cancelled {cancelled_count} pending deletions")
            else:
                log.debug("No pending deletions found to cancel")

            return cancelled_count

    def get_statistics(self) -> dict[str, int]:
        """
        Get current operation statistics.

        Returns:
            Dictionary containing operation statistics
        """
        with self._stats_lock:
            stats = self._stats.copy()

        with self.log_context(
                action="get_statistics",
                stats=stats
        ) as log:
            log.debug("Statistics retrieved")

        return stats

    def get_system_status(self) -> dict[str, Any]:
        """
        Get comprehensive system status information.

        Returns:
            Dictionary containing system status details
        """
        with self._deletion_lock:
            total_pending = sum(
                len(messages) for messages in self._user_pending_deletions.values()
            )
            users_with_pending = len(
                [uid for uid, msgs in self._user_pending_deletions.items() if msgs]
            )
            active_tasks_count = len(self._active_tasks)

        status = {
            "total_pending_deletions": total_pending,
            "users_with_pending_deletions": users_with_pending,
            "max_pending_per_user": self._max_pending_per_user,
            "active_tasks": active_tasks_count,
            "statistics": self.get_statistics(),
        }

        with self.log_context(
                action="get_system_status",
                **status
        ) as log:
            log.debug(
                f"System status retrieved - {total_pending} pending deletions, {users_with_pending} users affected")

        return status

    def __repr__(self) -> str:
        """Return a string representation of the manager."""
        with self._deletion_lock:
            total_pending = sum(
                len(messages) for messages in self._user_pending_deletions.values()
            )
        return f"<_MessageDeletionManager(pending={total_pending}, max_per_user={self._max_pending_per_user})>"


# Global singleton instance - this is the only public interface
deletion_manager = _MessageDeletionManager()

# Public type exports for type hints (optional)
DeletionResult = _DeletionResult
DeletionStatus = _DeletionStatus

# Export only the singleton instance
__all__ = ["deletion_manager", "DeletionResult", "DeletionStatus"]
