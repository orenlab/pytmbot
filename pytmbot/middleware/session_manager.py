#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import threading
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Any, Self, Final, ClassVar
from weakref import WeakValueDictionary

from pytmbot.logs import BaseComponent


class _StateFabric:
    """Class for managing user states."""

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


@dataclass
class _UserSession:
    """Represents a user session with type safety."""

    auth_state: str = _StateFabric.UNAUTHENTICATED
    totp_attempts: int = 0
    blocked_time: Optional[datetime] = None
    login_time: Optional[datetime] = None
    referer_uri: Optional[str] = None
    handler_type: Optional[str] = None

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


@dataclass
class SessionManager(BaseComponent):
    """
    Thread-safe session manager with modern Python practices.
    Implements singleton pattern with weak references for memory efficiency.
    """

    # Class variables with proper typing
    _instances: ClassVar[WeakValueDictionary[str, SessionManager]] = (
        WeakValueDictionary()
    )
    _lock: ClassVar[threading.RLock] = threading.RLock()

    # Instance configuration
    state_fabric: _StateFabric = field(default_factory=_StateFabric)
    cleanup_interval: int = 600  # seconds
    session_timeout: int = 10  # minutes
    max_totp_attempts: int = 5
    block_duration: int = 10  # minutes

    # Private fields
    _user_sessions: dict[int, _UserSession] = field(default_factory=dict, init=False)
    _cleanup_thread: Optional[threading.Thread] = field(default=None, init=False)
    _shutdown_event: threading.Event = field(
        default_factory=threading.Event, init=False
    )

    def __new__(cls, instance_name: str = "default") -> Self:
        """
        Thread-safe singleton implementation with named instances.
        """
        with cls._lock:
            if instance_name not in cls._instances:
                instance = super().__new__(cls)
                cls._instances[instance_name] = instance
            return cls._instances[instance_name]

    def __post_init__(self) -> None:
        """Initialize the session manager after dataclass initialization."""
        super().__init__("SessionManager")

        # Prevent re-initialization
        if hasattr(self, "_initialized"):
            return

        self._initialized = True
        self._start_cleanup_thread()

        with self.log_context(action="initialize") as log:
            log.info(
                "Session manager initialized",
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
                log.debug("Cleanup worker thread started")

                while not self._shutdown_event.is_set():
                    try:
                        self.clear_expired_sessions()
                    except Exception as e:
                        log.exception(
                            "Error during session cleanup", context={"error": str(e)}
                        )

                    # Use shutdown event for interruptible sleep
                    if self._shutdown_event.wait(timeout=self.cleanup_interval):
                        break

                log.debug("Cleanup worker thread stopped")

        self._cleanup_thread = threading.Thread(
            target=cleanup_worker, name="SessionManager-Cleanup", daemon=True
        )
        self._cleanup_thread.start()

    def _get_or_create_session(self, user_id: int) -> _UserSession:
        """Thread-safe session retrieval or creation."""
        with self._lock:
            if user_id not in self._user_sessions:
                self._user_sessions[user_id] = _UserSession()

                with self.log_context(user_id=user_id, action="create_session") as log:
                    log.debug("Created new session for user")

            return self._user_sessions[user_id]

    @contextmanager
    def session_context(self, user_id: int) -> Generator[_UserSession, None, None]:
        """Context manager for safe session access."""
        with self._lock:
            session = self._get_or_create_session(user_id)
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
                    "Authentication state changed",
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
                    "TOTP attempt recorded",
                    context={
                        "attempts": session.totp_attempts,
                        "max_attempts": self.max_totp_attempts,
                    },
                )

                # Auto-block if max attempts reached
                if session.totp_attempts >= self.max_totp_attempts:
                    self._block_user_internal(session, user_id)
                    log.warning("User blocked due to excessive TOTP attempts")

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
                log.debug("TOTP attempts reset")

    # Blocking management
    def _block_user_internal(self, session: _UserSession, user_id: int) -> None:
        """Internal method to block user (called with lock held)."""
        session.blocked_time = datetime.now() + timedelta(minutes=self.block_duration)
        session.auth_state = self.state_fabric.BLOCKED

    def set_blocked_time(
        self, user_id: int, duration_minutes: Optional[int] = None
    ) -> None:
        """Block user for specified duration."""
        duration = duration_minutes or self.block_duration

        with self.session_context(user_id) as session:
            session.blocked_time = datetime.now() + timedelta(minutes=duration)
            session.auth_state = self.state_fabric.BLOCKED

            with self.log_context(user_id=user_id, action="block_user") as log:
                log.warning(
                    "User blocked",
                    context={
                        "duration_minutes": duration,
                        "blocked_until": session.blocked_time.isoformat(),
                    },
                )

    def get_blocked_time(self, user_id: int) -> Optional[datetime]:
        """Get user's blocked time."""
        with self.session_context(user_id) as session:
            return session.blocked_time

    def is_blocked(self, user_id: int) -> bool:
        """Check if user is currently blocked."""
        with self.session_context(user_id) as session:
            if session.is_blocked_now():
                return True

            # Auto-unblock if time has passed
            if session.blocked_time and datetime.now() > session.blocked_time:
                session.blocked_time = None
                if session.auth_state == self.state_fabric.BLOCKED:
                    session.auth_state = self.state_fabric.UNAUTHENTICATED

                with self.log_context(user_id=user_id, action="auto_unblock") as log:
                    log.info("User automatically unblocked")

            return False

    # Session management
    def set_login_time(self, user_id: int) -> None:
        """Set login time to current time."""
        with self.session_context(user_id) as session:
            session.login_time = datetime.now()

            with self.log_context(user_id=user_id, action="login") as log:
                log.success("User login time set")

    def get_login_time(self, user_id: int) -> Optional[datetime]:
        """Get user's login time."""
        with self.session_context(user_id) as session:
            return session.login_time

    def is_session_expired(self, user_id: int) -> bool:
        """Check if user's session is expired."""
        with self.session_context(user_id) as session:
            expired = session.is_expired(self.session_timeout)

            if expired:
                with self.log_context(user_id=user_id, action="session_expired") as log:
                    log.warning(
                        "Session expired",
                        context={
                            "login_time": (
                                session.login_time.isoformat()
                                if session.login_time
                                else None
                            ),
                            "timeout_minutes": self.session_timeout,
                        },
                    )

            return expired

    def is_authenticated(self, user_id: int) -> bool:
        """Check if user is fully authenticated and session is valid."""
        with self.session_context(user_id) as session:
            is_auth = (
                session.auth_state == self.state_fabric.AUTHENTICATED
                and not self.is_blocked(user_id)
                and not session.is_expired(self.session_timeout)
            )

            with self.log_context(user_id=user_id, action="auth_check") as log:
                log.debug(
                    "Authentication check",
                    context={
                        "is_authenticated": is_auth,
                        "auth_state": session.auth_state,
                        "is_blocked": self.is_blocked(user_id),
                        "is_expired": session.is_expired(self.session_timeout),
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
                    "Referer data set",
                    context={"handler_type": handler_type, "referer_uri": referer_uri},
                )

    def get_referer_uri(self, user_id: int) -> Optional[str]:
        """Get referer URI for user."""
        with self.session_context(user_id) as session:
            return session.referer_uri

    def get_handler_type(self, user_id: int) -> Optional[str]:
        """Get handler type for user."""
        with self.session_context(user_id) as session:
            return session.handler_type

    def reset_referer_data(self, user_id: int) -> None:
        """Reset referer data for user."""
        with self.session_context(user_id) as session:
            session.referer_uri = None
            session.handler_type = None

            with self.log_context(user_id=user_id, action="reset_referer_data") as log:
                log.debug("Referer data reset")

    # Session cleanup
    def reset_session(self, user_id: int) -> None:
        """Reset entire session for user."""
        with self._lock:
            if user_id in self._user_sessions:
                del self._user_sessions[user_id]

                with self.log_context(user_id=user_id, action="reset_session") as log:
                    log.info("Session reset")

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
                        "Expired sessions cleared",
                        context={
                            "cleared_count": len(expired_users),
                            "expired_users": expired_users,
                        },
                    )

    # Statistics and monitoring
    def get_active_sessions_count(self) -> int:
        """Get count of active sessions."""
        with self._lock:
            return len(self._user_sessions)

    def get_session_stats(self) -> dict[str, Any]:
        """Get comprehensive session statistics."""
        with self._lock:
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

                if session.is_expired(self.session_timeout):
                    stats["expired_sessions"] += 1

            return stats

    def shutdown(self) -> None:
        """Gracefully shutdown the session manager."""
        with self.log_context(action="shutdown") as log:
            log.info("Shutting down session manager")

            self._shutdown_event.set()

            if self._cleanup_thread and self._cleanup_thread.is_alive():
                self._cleanup_thread.join(timeout=5.0)
                if self._cleanup_thread.is_alive():
                    log.warning("Cleanup thread did not stop gracefully")

            with self._lock:
                self._user_sessions.clear()

            log.success("Session manager shutdown complete")

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
                            "Unexpected error during cleanup", context={"error": str(e)}
                        )
            except Exception:
                pass
