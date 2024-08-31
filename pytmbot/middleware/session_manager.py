from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from pytmbot.logs import bot_logger


class _StateFabric:
    """ Class for managing user states. """
    authenticated: str = 'authenticated'
    processing: str = 'processing'
    blocked: str = 'blocked'
    unauthenticated: str = 'unauthenticated'

    @classmethod
    def valid_states(cls) -> set:
        """ Return a set of valid states. """
        return {cls.authenticated, cls.processing, cls.blocked, cls.unauthenticated}


@dataclass
class SessionManager:
    """
    A class for managing user sessions.
    """
    _instance: Optional['SessionManager'] = None
    __user_data: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    state_fabric: _StateFabric = _StateFabric()

    def __new__(cls) -> 'SessionManager':
        """
        Creates a new instance of the SessionManager class if it doesn't exist.

        This method is used to implement the Singleton design pattern, ensuring that only one instance of the
        SessionManager class is created.

        Returns:
            SessionManager: The instance of the SessionManager class.
        """
        if cls._instance is None:
            cls._instance = super(SessionManager, cls).__new__(cls)
        return cls._instance

    def _get_user_data(self, user_id: int) -> dict:
        if user_id not in self.user_data:
            self.user_data[user_id] = {'auth_state': self.state_fabric.unauthenticated}
        return self.user_data[user_id]

    @property
    def user_data(self) -> Dict[int, Dict[str, Any]]:
        return self.__user_data

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
        bot_logger.debug(f"Setting authentication state for user {user_id} to {state}")
        self._get_user_data(user_id)['auth_state'] = state

    def get_auth_state(self, user_id: int) -> Optional[str]:
        """
        Returns the authentication state for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            Optional[str]: The authentication state if found, otherwise None.
        """
        return self._get_user_data(user_id).get('auth_state', None)

    def set_totp_attempts(self, user_id: int) -> None:
        """
        Sets the TOTP attempts for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            None
        """
        user_data = self._get_user_data(user_id)
        user_data['totp_attempts'] = user_data.get('totp_attempts', 0) + 1
        bot_logger.debug(f"Setting TOTP attempts for user {user_id} to {user_data['totp_attempts']}")

    def get_totp_attempts(self, user_id: int) -> int:
        """
        Returns the TOTP attempts for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            int: The TOTP attempts for the user.
        """
        return self._get_user_data(user_id).get('totp_attempts', 0)

    def reset_totp_attempts(self, user_id: int) -> None:
        """
        Resets the TOTP attempts for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            None
        """
        user_data = self._get_user_data(user_id)
        user_data['totp_attempts'] = 0
        bot_logger.debug(f"Resetting TOTP attempts for user {user_id}")

    def set_blocked_time(self, user_id: int) -> None:
        """
        Set the blocked time for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            None
        """
        self._get_user_data(user_id)['blocked_time'] = datetime.now() + timedelta(minutes=5)
        bot_logger.debug(f"Setting blocked time for user {user_id}")

    def get_blocked_time(self, user_id: int) -> Optional[datetime]:
        """
        Returns the blocked time for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            Optional[datetime]: The blocked time for the user, or None if not found.
        """
        return self._get_user_data(user_id).get('blocked_time', None)

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
                self._get_user_data(user_id)['blocked_time'] = None
                bot_logger.debug(f"User {user_id} is no longer blocked")
                return False
            bot_logger.debug(f"User {user_id} is currently blocked")
            return True
        bot_logger.debug(f"User {user_id} is not blocked")
        return False

    def is_authenticated(self, user_id: int) -> bool:
        """
        Checks if a user is authenticated.

        Args:
            user_id (int): The ID of the user.

        Returns:
            bool: True if the user is authenticated, False otherwise.
        """
        return (self.get_auth_state(user_id) == self.state_fabric.authenticated and
                not self.is_blocked(user_id) and
                not self.is_session_expired(user_id))

    def set_login_time(self, user_id: int) -> None:
        """
        Set the login time for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            None
        """
        self._get_user_data(user_id)['login_time'] = datetime.now()

    def get_login_time(self, user_id: int) -> Optional[datetime]:
        """
        Returns the login time for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            Optional[datetime]: The login time for the user, or None if not found.
        """
        return self._get_user_data(user_id).get('login_time', None)

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
            expired = datetime.now() > login_time + timedelta(minutes=5)
            bot_logger.debug(f"User {user_id} session expired: {expired}")
            return False
        bot_logger.debug(f"User {user_id} session login time not found")
        return True

    def set_referer_uri_and_handler_type_for_user(self, user_id: int, handler_type: str, referer_uri: str) -> None:
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
        user_data['referer_uri'] = referer_uri
        user_data['handler_type'] = handler_type

    def get_referer_uri_for_user(self, user_id: int) -> Optional[str]:
        """
        Returns the referer URI for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            Optional[str]: The referer URI for the user, or None if not found.
        """
        return self._get_user_data(user_id).get('referer_uri', None)

    def get_handler_type_for_user(self, user_id: int) -> Optional[str]:
        """
        Retrieves the handler type for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            Optional[str]: The handler type for the user, or None if not found.
        """
        return self._get_user_data(user_id).get('handler_type', None)

    def reset_referer_uri_and_handler_type_for_user(self, user_id: int) -> None:
        """
        Resets the referer URI and handler type for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            None
        """
        user_data = self._get_user_data(user_id)
        user_data['referer_uri'] = None
        user_data['handler_type'] = None
