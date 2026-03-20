#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import itertools
import threading
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import ClassVar, Final
from weakref import WeakValueDictionary

from pytmbot.logs import BaseComponent
from pytmbot.utils import mask_user_id


class _StateFabric:
    """Class for managing user states."""

    __slots__ = ()

    # Using Final for immutable constants
    AUTHENTICATED: Final[str] = "authenticated"
    PROCESSING: Final[str] = "processing"
    BLOCKED: Final[str] = "blocked"
    UNAUTHENTICATED: Final[str] = "unauthenticated"

    @classmethod
    def valid_states(cls) -> frozenset[str]:
        """Return a frozenset of valid states for immutability."""
        return frozenset(
            {cls.AUTHENTICATED, cls.PROCESSING, cls.BLOCKED, cls.UNAUTHENTICATED}
        )


@dataclass(slots=True)
class _UserSession:
    """Represents a user session with type safety."""

    auth_state: str = _StateFabric.UNAUTHENTICATED
    totp_attempts: int = 0
    blocked_time: datetime | None = None
    login_time: datetime | None = None
    referer_uri: str | None = None
    handler_type: str | None = None

    def is_expired(self, timeout_minutes: int) -> bool:
        """Check if session is expired."""
        if not self.login_time:
            return True
        return datetime.now() > self.login_time + timedelta(minutes=timeout_minutes)

    def is_blocked_now(self) -> bool:
        """Check if user is currently blocked."""
        if not self.blocked_time:
            return False
        return datetime.now() <= self.blocked_time


class SessionManager(BaseComponent):
    """
    Thread-safe session manager with modern Python practices.
    Implements singleton pattern with weak references for memory efficiency.
    """

    __slots__ = (
        "state_fabric",
        "cleanup_interval",
        "session_timeout",
        "max_totp_attempts",
        "block_duration",
        "_user_sessions",
        "_cleanup_thread",
        "_shutdown_event",
        "_initialized",
        "__weakref__",
    )

    # Class variables with proper typing
    _instances: ClassVar[WeakValueDictionary[str, SessionManager]] = (
        WeakValueDictionary()
    )
    _lock: ClassVar[threading.RLock] = threading.RLock()

    # Default configuration
    _DEFAULT_CLEANUP_INTERVAL: Final[int] = 600  # seconds
    _DEFAULT_SESSION_TIMEOUT: Final[int] = 10  # minutes
    _DEFAULT_MAX_TOTP_ATTEMPTS: Final[int] = 5
    _DEFAULT_BLOCK_DURATION: Final[int] = 10  # minutes
    _MAX_SESSIONS: Final[int] = 10_000

    state_fabric: _StateFabric
    cleanup_interval: int
    session_timeout: int
    max_totp_attempts: int
    block_duration: int

    _user_sessions: dict[int, _UserSession]
    _cleanup_thread: threading.Thread | None
    _shutdown_event: threading.Event
    _initialized: bool

    def __new__(cls, instance_name: str = "default") -> SessionManager:
        """
        Thread-safe singleton implementation with named instances.
        """
        with cls._lock:
            if instance_name not in cls._instances:
                instance = super().__new__(cls)
                cls._instances[instance_name] = instance
            return cls._instances[instance_name]

    def __init__(
        self,
        instance_name: str = "default",
        *,
        cleanup_interval: int | None = None,
        session_timeout: int | None = None,
        max_totp_attempts: int | None = None,
        block_duration: int | None = None,
    ) -> None:
        """Initialize singleton state once without resetting active sessions."""
        del instance_name  # kept for backward-compatible constructor signature

        if getattr(self, "_initialized", False):
            return

        super().__init__("SessionManager")

        self.state_fabric = _StateFabric()
        self.cleanup_interval = (
            cleanup_interval
            if cleanup_interval is not None
            else self._DEFAULT_CLEANUP_INTERVAL
        )
        self.session_timeout = (
            session_timeout
            if session_timeout is not None
            else self._DEFAULT_SESSION_TIMEOUT
        )
        self.max_totp_attempts = (
            max_totp_attempts
            if max_totp_attempts is not None
            else self._DEFAULT_MAX_TOTP_ATTEMPTS
        )
        self.block_duration = (
            block_duration
            if block_duration is not None
            else self._DEFAULT_BLOCK_DURATION
        )

        self._user_sessions = {}
        self._cleanup_thread = None
        self._shutdown_event = threading.Event()
        self._initialized = True
        self._start_cleanup_thread()

        with self.log_context(action="initialize") as log:
            log.info(
                "bot.session.manager.init",
                context={
                    "cleanup_interval": self.cleanup_interval,
                    "session_timeout": self.session_timeout,
                    "max_totp_attempts": self.max_totp_attempts,
                },
            )

    def _start_cleanup_thread(self) -> None:
        """Start background cleanup thread with proper error handling."""
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            return

        def cleanup_worker() -> None:
            with self.log_context(action="cleanup_worker") as log:
                log.debug("bot.session.cleanup.worker.start")

                while not self._shutdown_event.is_set():
                    try:
                        self.clear_expired_sessions()
                    except Exception as e:
                        log.error(
                            "bot.session.cleanup.fail",
                            context={
                                "error": str(e),
                                "error_type": type(e).__name__,
                            },
                        )

                    # Use shutdown event for interruptible sleep
                    if self._shutdown_event.wait(timeout=self.cleanup_interval):
                        break

                log.debug("bot.session.cleanup.worker.stop")

        self._cleanup_thread = threading.Thread(
            target=cleanup_worker, name="SessionManager-Cleanup", daemon=True
        )
        self._cleanup_thread.start()

    def _get_or_create_session_locked(self, user_id: int) -> _UserSession:
        """
        Retrieve or create user session with ``self._lock`` already held.
        """
        if user_id not in self._user_sessions:
            evicted_count = self._evict_sessions_if_needed()
            self._user_sessions[user_id] = _UserSession()

            with self.log_context(user_id=user_id, action="create_session") as log:
                log.debug(
                    "bot.session.create.user.debug",
                    context={
                        "evicted_sessions": evicted_count,
                        "total_sessions": len(self._user_sessions),
                    },
                )

        return self._user_sessions[user_id]

    def _evict_sessions_if_needed(self) -> int:
        """
        Enforce hard cap for in-memory sessions.

        Must be called with ``self._lock`` held.
        """
        overflow = len(self._user_sessions) - self._MAX_SESSIONS + 1
        if overflow <= 0:
            return 0

        evicted = 0

        expired_users = [
            uid
            for uid, session in self._user_sessions.items()
            if session.is_expired(self.session_timeout)
        ]
        for uid in expired_users:
            del self._user_sessions[uid]
            evicted += 1

        overflow = len(self._user_sessions) - self._MAX_SESSIONS + 1
        if overflow <= 0:
            return evicted

        non_authenticated_users = [
            uid
            for uid, session in self._user_sessions.items()
            if session.auth_state != self.state_fabric.AUTHENTICATED
        ]
        for uid in non_authenticated_users[:overflow]:
            del self._user_sessions[uid]
            evicted += 1

        overflow = len(self._user_sessions) - self._MAX_SESSIONS + 1
        if overflow <= 0:
            return evicted

        for uid in list(itertools.islice(self._user_sessions, overflow)):
            del self._user_sessions[uid]
            evicted += 1

        return evicted

    @contextmanager
    def session_context(self, user_id: int) -> Generator[_UserSession, None, None]:
        """Context manager for safe session access."""
        with self._lock:
            session = self._get_or_create_session_locked(user_id)
            yield session

    # Authentication state management
    def set_auth_state(self, user_id: int, state: str) -> None:
        """Set authentication state with validation."""
        if state not in self.state_fabric.valid_states():
            raise ValueError(
                f"Invalid state: {state}. Valid states: {self.state_fabric.valid_states()}"
            )

        with self.session_context(user_id) as session:
            old_state = session.auth_state
            session.auth_state = state

            with self.log_context(user_id=user_id, action="set_auth_state") as log:
                log.info(
                    "bot.session.authentication.state.info",
                    context={"old_state": old_state, "new_state": state},
                )

    def get_auth_state(self, user_id: int) -> str:
        """Get authentication state."""
        with self.session_context(user_id) as session:
            return session.auth_state

    # TOTP management
    def increment_totp_attempts(self, user_id: int) -> int:
        """Increment TOTP attempts and return new count."""
        with self.session_context(user_id) as session:
            session.totp_attempts += 1

            with self.log_context(
                user_id=user_id, action="increment_totp_attempts"
            ) as log:
                log.warning(
                    "bot.session.totp.attempt.warn",
                    context={
                        "attempts": session.totp_attempts,
                        "max_attempts": self.max_totp_attempts,
                    },
                )

                # Auto-block if max attempts reached
                if session.totp_attempts >= self.max_totp_attempts:
                    self._block_user_internal(session, user_id)
                    log.warning("bot.session.user.blocked.deny")

            return session.totp_attempts

    def get_totp_attempts(self, user_id: int) -> int:
        """Get current TOTP attempts count."""
        with self.session_context(user_id) as session:
            return session.totp_attempts

    def reset_totp_attempts(self, user_id: int) -> None:
        """Reset TOTP attempts counter."""
        with self.session_context(user_id) as session:
            session.totp_attempts = 0

            with self.log_context(user_id=user_id, action="reset_totp_attempts") as log:
                log.debug("bot.session.totp.attempts.debug")

    # Blocking management
    def _block_user_internal(self, session: _UserSession, user_id: int) -> None:
        """Internal method to block user (called with lock held)."""
        session.blocked_time = datetime.now() + timedelta(minutes=self.block_duration)
        session.auth_state = self.state_fabric.BLOCKED

    def set_blocked_time(
        self, user_id: int, duration_minutes: int | None = None
    ) -> None:
        """Block user for specified duration."""
        duration = duration_minutes or self.block_duration

        with self.session_context(user_id) as session:
            session.blocked_time = datetime.now() + timedelta(minutes=duration)
            session.auth_state = self.state_fabric.BLOCKED

            with self.log_context(user_id=user_id, action="block_user") as log:
                log.warning(
                    "bot.session.user.blocked.deny",
                    context={
                        "duration_minutes": duration,
                        "blocked_until": session.blocked_time.isoformat(),
                    },
                )

    def _auto_unblock_if_due(self, _user_id: int, session: _UserSession) -> bool:
        """Unblock user when block timeout has elapsed."""
        blocked_time = session.blocked_time
        if blocked_time is None or datetime.now() <= blocked_time:
            return False

        session.blocked_time = None
        if session.auth_state == self.state_fabric.BLOCKED:
            session.auth_state = self.state_fabric.UNAUTHENTICATED
        return True

    def get_blocked_time(self, user_id: int) -> datetime | None:
        """Get user's blocked time."""
        with self.session_context(user_id) as session:
            return session.blocked_time

    def is_blocked(self, user_id: int) -> bool:
        """Check if user is currently blocked."""
        unblocked = False
        with self.session_context(user_id) as session:
            if session.is_blocked_now():
                return True

            unblocked = self._auto_unblock_if_due(user_id, session)

        if unblocked:
            with self.log_context(user_id=user_id, action="auto_unblock") as log:
                log.info("bot.session.user.automatically.unblocked.ok")
        return False

    # Session management
    def set_login_time(self, user_id: int) -> None:
        """Set login time to current time."""
        with self.session_context(user_id) as session:
            session.login_time = datetime.now()

            with self.log_context(user_id=user_id, action="login") as log:
                log.success("bot.session.user.login.ok")

    def is_authenticated(self, user_id: int) -> bool:
        """Check if user is fully authenticated and session is valid."""
        with self.session_context(user_id) as session:
            is_blocked = session.is_blocked_now()

            if not is_blocked:
                self._auto_unblock_if_due(user_id, session)

            is_expired = session.is_expired(self.session_timeout)
            is_auth = (
                session.auth_state == self.state_fabric.AUTHENTICATED
                and not is_blocked
                and not is_expired
            )

            with self.log_context(user_id=user_id, action="auth_check") as log:
                log.debug(
                    "bot.session.authentication.check.debug",
                    context={
                        "is_authenticated": is_auth,
                        "auth_state": session.auth_state,
                        "is_blocked": is_blocked,
                        "is_expired": is_expired,
                    },
                )

            return is_auth

    # Referer and handler management
    def set_referer_data(
        self, user_id: int, handler_type: str, referer_uri: str
    ) -> None:
        """Set referer URI and handler type."""
        with self.session_context(user_id) as session:
            session.referer_uri = referer_uri
            session.handler_type = handler_type

            with self.log_context(user_id=user_id, action="set_referer_data") as log:
                log.debug(
                    "bot.session.referer.data.debug",
                    context={"handler_type": handler_type, "referer_uri": referer_uri},
                )

    def get_referer_uri(self, user_id: int) -> str | None:
        """Get referer URI for user."""
        with self.session_context(user_id) as session:
            return session.referer_uri

    def get_handler_type(self, user_id: int) -> str | None:
        """Get handler type for user."""
        with self.session_context(user_id) as session:
            return session.handler_type

    def reset_referer_data(self, user_id: int) -> None:
        """Reset referer data for user."""
        with self.session_context(user_id) as session:
            session.referer_uri = None
            session.handler_type = None

            with self.log_context(user_id=user_id, action="reset_referer_data") as log:
                log.debug("bot.session.referer.data.debug")

    # Session cleanup

    def clear_expired_sessions(self) -> None:
        """Clear all expired sessions."""
        with self._lock:
            expired_users = [
                user_id
                for user_id, session in self._user_sessions.items()
                if session.is_expired(self.session_timeout)
            ]

            if expired_users:
                for user_id in expired_users:
                    del self._user_sessions[user_id]

                with self.log_context(action="cleanup_expired_sessions") as log:
                    log.info(
                        "bot.session.expired.sessions.info",
                        context={
                            "cleared_count": len(expired_users),
                            "expired_users": [
                                mask_user_id(user_id) for user_id in expired_users
                            ],
                        },
                    )

    # Statistics and monitoring

    def get_session_stats(self) -> dict[str, int]:
        """Get comprehensive session statistics.

        Evicts expired sessions inline to avoid stale data polluting
        health checks between cleanup-thread runs.
        """
        with self._lock:
            expired_users = [
                uid
                for uid, s in self._user_sessions.items()
                if s.is_expired(self.session_timeout)
            ]
            for uid in expired_users:
                del self._user_sessions[uid]

            stats = {
                "total_sessions": len(self._user_sessions),
                "authenticated_sessions": 0,
                "blocked_sessions": 0,
                "expired_sessions": 0,
                "processing_sessions": 0,
            }

            for session in self._user_sessions.values():
                if session.auth_state == self.state_fabric.AUTHENTICATED:
                    stats["authenticated_sessions"] += 1
                elif session.auth_state == self.state_fabric.BLOCKED:
                    stats["blocked_sessions"] += 1
                elif session.auth_state == self.state_fabric.PROCESSING:
                    stats["processing_sessions"] += 1

            stats["evicted_sessions"] = len(expired_users)

            return stats

    def shutdown(self) -> None:
        """Gracefully shutdown the session manager."""
        with self.log_context(action="shutdown") as log:
            log.info("bot.session.shutting.manager.info")

            self._shutdown_event.set()

            if self._cleanup_thread and self._cleanup_thread.is_alive():
                self._cleanup_thread.join(timeout=5.0)
                if self._cleanup_thread.is_alive():
                    log.warning("bot.session.cleanup.thread.warn")

            with self._lock:
                self._user_sessions.clear()

            log.success("bot.session.manager.stop")

    def __del__(self) -> None:
        """Cleanup on object destruction."""
        try:
            if hasattr(self, "_initialized") and hasattr(self, "_shutdown_event"):
                if not self._shutdown_event.is_set():
                    self.shutdown()
        except (AttributeError, RuntimeError, TypeError):
            pass
        except Exception as e:
            # Log unexpected errors if logging is still available
            try:
                if hasattr(self, "log_context"):
                    with self.log_context(action="destructor_error") as log:
                        log.debug(
                            "bot.session.unexpected.fail", context={"error": str(e)}
                        )
            except Exception:
                pass
