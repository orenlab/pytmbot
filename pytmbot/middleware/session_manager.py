from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from pytmbot.logs import bot_logger


class _StateFabric:
    """ Class for managing user states. """
    authenticated = 'authenticated'
    processing = 'processing'
    blocked = 'blocked'
    unauthenticated = 'unauthenticated'


@dataclass
class SessionManager:
    """
    A class for managing user sessions.
    """
    _instance = None
    __user_data: dict = field(default_factory=dict)
    state_fabric = _StateFabric()

    def __new__(cls):
        """
        Creates a new instance of the SessionManager class if it doesn't exist.

        This method is used to implement the Singleton design pattern, ensuring that only one instance of the
        SessionManager class is created.

        Returns:
            SessionManager: The instance of the SessionManager class.
        """
        # Check if the instance of the SessionManager class already exists
        if cls._instance is None:
            # If not, create a new instance using the superclass's __new__ method
            cls._instance = super(SessionManager, cls).__new__(cls)
        # Return the instance of the SessionManager class
        return cls._instance

    @property
    def user_data(self) -> dict:
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
        bot_logger.debug(f"Setting authentication state for user {user_id} to {state}")
        self.user_data.setdefault(user_id, {})['auth_state'] = state

    def get_auth_state(self, user_id: int) -> Optional[str]:
        """
        Returns the authentication state for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            Optional[str]: The authentication state if found, otherwise None.
        """
        try:
            return self.user_data.get(user_id, {}).get('auth_state')
        except KeyError:
            return None

    def set_totp_attempts(self, user_id: int) -> None:
        """
        Sets the TOTP attempts for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            None
        """
        if user_id in self.user_data:
            self.user_data[user_id]['totp_attempts'] = self.user_data[user_id].get('totp_attempts', 0) + 1
        else:
            self.user_data[user_id] = {'totp_attempts': 1}
        bot_logger.debug(f"Setting TOTP attempts for user {user_id} to {self.user_data[user_id]['totp_attempts']}")

    def get_totp_attempts(self, user_id: int) -> int:
        """
        Returns the TOTP attempts for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            int: The TOTP attempts for the user.
        """
        return self.user_data[user_id].get('totp_attempts', 0) if user_id in self.user_data else 0

    def reset_totp_attempts(self, user_id: int) -> None:
        """
        Resets the TOTP attempts for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            None
        """
        self.user_data[user_id] = {'totp_attempts': None}
        bot_logger.debug(f"Resetting TOTP attempts for user {user_id}")

    def set_blocked_time(self, user_id: int) -> None:
        """
        Set the blocked time for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            None: This function does not return anything.
        """
        self.user_data[user_id].update({'blocked_time': datetime.now() + timedelta(minutes=5)})
        bot_logger.debug(f"Setting blocked time for user {user_id} to {self.user_data[user_id]['blocked_time']}")

    def get_blocked_time(self, user_id: int) -> Optional[datetime]:
        """
        Returns the blocked time for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            Optional[datetime]: The blocked time for the user, or None if not found.
        """
        try:
            return self.user_data[user_id]['blocked_time']
        except KeyError:
            return None

    def is_blocked(self, user_id: int) -> bool:
        """
        Checks if a user is blocked.

        Args:
            user_id (int): The ID of the user.

        Returns:
            bool: True if the user is blocked, False otherwise.
        """
        try:
            bot_logger.debug(f"Checking if user {user_id} is blocked")
            return self.get_blocked_time(user_id) is not None
        except KeyError:
            return False

    def is_authenticated(self, user_id: int) -> bool:
        """
        Checks if a user is authenticated.

        Args:
            user_id (int): The ID of the user.

        Returns:
            bool: True if the user is authenticated, False otherwise.
        """
        try:
            bot_logger.debug(f"Checking if user {user_id} is authenticated")
            return self.get_auth_state(user_id) == self.state_fabric.authenticated and not self.is_blocked(
                user_id) and not self.is_session_expired(user_id)
        except KeyError:
            return False

    def set_login_time(self, user_id: int) -> None:
        """
        Set the login time for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            None: This function does not return anything.
        """
        self.user_data[user_id].update({'login_time': datetime.now()})

    def get_login_time(self, user_id: int) -> Optional[datetime]:
        """
        Returns the login time for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            Optional[datetime]: The login time for the user, or None if not found.
        """
        bot_logger.debug(f"Getting login time for user {user_id}")
        return self.user_data[user_id].get('login_time', None)

    def is_session_expired(self, user_id: int) -> bool:
        """
        Checks if a user's session is expired.

        Args:
            user_id (int): The ID of the user.

        Returns:
            bool: True if the user's session is expired, False otherwise.
        """
        bot_logger.debug(f"Checking if user {user_id} session is expired")
        return datetime.now() > self.get_login_time(user_id) + timedelta(minutes=5)

    def set_referer_uri_and_handler_type_for_user(
            self, user_id: int, handler_type: str, referer_uri: str) -> None:
        """
        Set the referer URI and handler type for a given user ID.

        Args:
            user_id (int): The ID of the user.
            handler_type (str): The type of the handler.
            referer_uri (str): The URI of the referer.

        Returns:
            None: This function does not return anything.
        """
        self.user_data.setdefault(user_id, {})['referer_uri'] = referer_uri
        self.user_data.setdefault(user_id, {})['handler_type'] = handler_type

    def get_referer_uri_for_user(self, user_id: int) -> Optional[str]:
        """
        Returns the referer URI for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            Optional[str]: The referer URI for the user, or None if not found.
        """
        return self.user_data[user_id].get('referer_uri', None)

    def get_handler_type_for_user(self, user_id: int) -> Optional[str]:
        """
        Retrieves the handler type for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            Optional[str]: The handler type for the user, or None if not found.
        """
        return self.user_data[user_id].get('handler_type', None)

    def reset_referer_uri_and_handler_type_for_user(self, user_id: int) -> None:

        """
        Resets the referer URI and handler type for a given user ID.

        Args:
            user_id (int): The ID of the user.

        Returns:
            None
        """
        self.user_data[user_id]['referer_uri'] = None
        self.user_data[user_id]['handler_type'] = None
