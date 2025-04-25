from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional, Any, Self

from pytmbot.logs import Logger

logger = Logger()


class _StateFabric:
    """Class for managing user states."""

    authenticated: str = "authenticated"
    processing: str = "processing"
    blocked: str = "blocked"
    unauthenticated: str = "unauthenticated"

    @classmethod
    def valid_states(cls) -> set[str]:
        """Return a set of valid states."""
        return {cls.authenticated, cls.processing, cls.blocked, cls.unauthenticated}


@dataclass
class SessionManager:
    """
    A class for managing user sessions.
    """
    _instance: Optional[Self] = None
    state_fabric: _StateFabric = _StateFabric()
    _cleanup_interval: int = 600  # Cleanup expired sessions interval in seconds
    session_timeout: int = 10  # Session timeout in minutes

    def __init__(self):
        self._user_data = {}

    def __new__(cls) -> SessionManager:
        """
        Creates a new instance of the SessionManager class if it doesn't exist.

        This method is used to implement the Singleton design pattern, ensuring that only one instance of the
        SessionManager class is created.
        """
        if cls._instance is None:
            cls._instance = super(SessionManager, cls).__new__(cls)
            cls._instance._start_cleanup_thread()
        return cls._instance

    def _start_cleanup_thread(self) -> None:
        """
        Starts a background thread that periodically cleans up expired sessions.
        The thread will continue running at regular intervals.
        """

        def run_cleanup():
            while True:
                try:
                    logger.debug("Session Manager job started: session periodic cleanup")
                    self.clear_expired_sessions()
                    logger.debug("Session Manager job completed: session periodic cleanup")
                except Exception as e:
                    logger.exception(f"Error during session cleanup: {e}")
                # Pause for the interval duration
                threading.Event().wait(self._cleanup_interval)

        # Create and start a daemon thread
        cleanup_thread = threading.Thread(target=run_cleanup)
        cleanup_thread.daemon = True
        cleanup_thread.start()

    def _get_user_data(self, user_id: int) -> dict[str, Any]:
        """
        Retrieves or initializes user data by user_id.

        Args:
            user_id (int): The ID of the user.

        Returns:
            dict[str, Any]: The user data.
        """
        if user_id not in self._user_data:
            self._user_data[user_id] = {
                "auth_state": self.state_fabric.unauthenticated
            }
        return self._user_data[user_id]

    @property
    def user_data(self) -> dict[int, dict[str, Any]]:
        return self._user_data

    def set_auth_state(self, user_id: int, state: str) -> None:
        """
        Sets the authentication state for a given user ID.

        Args:
            user_id (int): The ID of the user.
            state (str): The authentication state. Must be one of the states in self.state_fabric.

        Returns:
            None

        Raises:
            ValueError: If the state is not a valid authentication state.
        """
        if state not in self.state_fabric.valid_states():
            raise ValueError(f"Invalid state: {state}")
        logger.debug(f"Setting authentication state for user {user_id} to {state}")
        self._get_user_data(user_id)["auth_state"] = state

    def get_auth_state(self, user_id: int) -> Optional[str]:
        """
        Returns the authentication state for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            Optional[str]: The authentication state if found, otherwise None.
        """
        return self._get_user_data(user_id).get("auth_state", None)

    def set_totp_attempts(self, user_id: int) -> None:
        """
        Sets the TOTP attempts for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            None
        """
        user_data = self._get_user_data(user_id)
        user_data["totp_attempts"] = user_data.get("totp_attempts", 0) + 1
        logger.debug(
            f"Setting TOTP attempts for user {user_id} to {user_data['totp_attempts']}"
        )

    def get_totp_attempts(self, user_id: int) -> int:
        """
        Returns the TOTP attempts for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            int: The TOTP attempts for the user.
        """
        return self._get_user_data(user_id).get("totp_attempts", 0)

    def reset_totp_attempts(self, user_id: int) -> None:
        """
        Resets the TOTP attempts for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            None
        """
        self._get_user_data(user_id)["totp_attempts"] = 0
        logger.debug(f"Resetting TOTP attempts for user {user_id}")

    def set_blocked_time(self, user_id: int) -> None:
        """
        Set the blocked time for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            None
        """
        self._get_user_data(user_id)["blocked_time"] = datetime.now() + timedelta(
            minutes=10
        )
        logger.debug(f"Setting blocked time for user {user_id}")

    def get_blocked_time(self, user_id: int) -> Optional[datetime]:
        """
        Returns the blocked time for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            Optional[datetime]: The blocked time for the user, or None if not found.
        """
        return self._get_user_data(user_id).get("blocked_time", None)

    def is_blocked(self, user_id: int) -> bool:
        """
        Checks if a user is blocked.

        Args:
            user_id (int): The ID of the user.

        Returns:
            bool: True if the user is blocked, False otherwise.
        """
        blocked_time = self.get_blocked_time(user_id)
        if blocked_time:
            if datetime.now() > blocked_time:
                # Unblock user if blocked time has passed
                self._get_user_data(user_id)["blocked_time"] = None
                logger.debug(f"User {user_id} is no longer blocked")
                return False
            logger.debug(f"User {user_id} is currently blocked")
            return True
        logger.debug(f"User {user_id} is not blocked")
        return False

    def is_authenticated(self, user_id: int) -> bool:
        """
        Checks if a user is authenticated.

        Args:
            user_id (int): The ID of the user.

        Returns:
            bool: True if the user is authenticated, False otherwise.
        """
        return (
                self.get_auth_state(user_id) == self.state_fabric.authenticated
                and not self.is_blocked(user_id)
                and not self.is_session_expired(user_id)
        )

    def set_login_time(self, user_id: int) -> None:
        """
        Set the login time for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            None
        """
        self._get_user_data(user_id)["login_time"] = datetime.now()

    def get_login_time(self, user_id: int) -> Optional[datetime]:
        """
        Returns the login time for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            Optional[datetime]: The login time for the user, or None if not found.
        """
        return self._get_user_data(user_id).get("login_time", None)

    def is_session_expired(self, user_id: int) -> bool:
        """
        Checks if a user's session is expired.

        Args:
            user_id (int): The ID of the user.

        Returns:
            bool: True if the user's session is expired, False otherwise.
        """
        login_time = self.get_login_time(user_id)
        if login_time:
            expired = datetime.now() > login_time + timedelta(
                minutes=self.session_timeout
            )
            logger.debug(f"User {user_id} session expired: {expired}")
            return expired
        logger.debug(f"User {user_id} session login time not found")
        return True

    def set_referer_uri_and_handler_type_for_user(
            self, user_id: int, handler_type: str, referer_uri: str
    ) -> None:
        """
        Set the referer URI and handler type for a given user ID.

        Args:
            user_id (int): The ID of the user.
            handler_type (str): The type of the handler.
            referer_uri (str): The URI of the referer.

        Returns:
            None
        """
        user_data = self._get_user_data(user_id)
        user_data["referer_uri"] = referer_uri
        user_data["handler_type"] = handler_type

    def get_referer_uri_for_user(self, user_id: int) -> Optional[str]:
        """
        Returns the referer URI for a given user ID.

        Args:
            user_id (int): The ID of the user.
            Returns:
                Optional[str]: The referer URI for the user, or None if not found.
        """
        return self._get_user_data(user_id).get("referer_uri", None)

    def get_handler_type_for_user(self, user_id: int) -> Optional[str]:
        """
        Returns the handler type for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            Optional[str]: The handler type for the user, or None if not found.
        """
        return self._get_user_data(user_id).get("handler_type", None)

    def reset_session(self, user_id: int) -> None:
        """
        Resets the session for a given user ID by clearing all session-related data.

        Args:
            user_id (int): The ID of the user.

        Returns:
            None
        """
        if user_id in self._user_data:
            logger.debug(f"Resetting session for user {user_id}")
            self._user_data.pop(user_id)

    def clear_expired_sessions(self) -> None:
        """
        Clears expired user sessions.

        This method iterates through all user sessions and removes those that have expired.

        Returns:
            None
        """
        if not hasattr(self, '_user_data'):
            logger.warning(
                "User data attribute is missing. Initializing user data storage. "
                "This is expected during the application's first run or reinitialization."
            )
            self._user_data = {}
        else:
            expired_users = [
                user_id
                for user_id, user_data in self._user_data.items()
                if self.is_session_expired(user_id)
            ]
            for user_id in expired_users:
                logger.debug(f"Clearing expired session for user {user_id}")
                self._user_data.pop(user_id, None)

    def reset_referer_uri_and_handler_type_for_user(self, user_id: int) -> None:
        """
        Resets the referer URI and handler type for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            None
        """
        user_data = self._get_user_data(user_id)
        user_data["referer_uri"] = None
        user_data["handler_type"] = None
        logger.debug(f"Resetting referer URI and handler type for user {user_id}")
