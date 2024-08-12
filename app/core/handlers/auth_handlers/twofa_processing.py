#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from datetime import datetime

from telebot.types import Message

from app import config, bot_logger, session_manager
from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_handler_session
from app.utilities.totp import TwoFactorAuthenticator


class TwoFAStartHandler(HandlerConstructor):
    """Class to handle auth required messages."""

    def handle(self) -> None:
        """
        Handle the 'Enter 2FA code' message.

        This method sets up a message handler for the 'Enter 2FA code' message. It checks if the sender's ID is in the
        list of allowed admin IDs. If it is, it sends a message with an inline keyboard to the user,
        asking them to enter their 2FA code.

        """
        allowed_admins_ids = set(self.config.allowed_admins_ids)

        @self.bot.message_handler(regexp='Enter 2FA code',
                                  func=lambda message: message.from_user.id in allowed_admins_ids)
        @logged_handler_session
        def handle_twofa_message(message: Message):
            try:
                user_id = message.from_user.id
                if session_manager.is_blocked(user_id):
                    self._handle_blocked_user(message)
                    return
                session_manager.set_auth_state(user_id, session_manager.state_fabric.processing)
                self._send_totp_code_message(message)
            except Exception as err:
                bot_logger.error(err, exc_info=True)

        @self.bot.message_handler(regexp=r"[0-9]{6}$",
                                  func=lambda message:
                                  message.from_user.id in config.allowed_admins_ids and session_manager.get_auth_state(
                                      message.from_user.id) == session_manager.state_fabric.processing)
        @logged_handler_session
        def handle_totp_code_verification(message: Message) -> None:
            """
            Handle the TOTP code verification message.

            Args:
                message (telebot.types.Message): The message object received from the user.

            Returns:
                None
            """
            user_id: int = message.from_user.id
            totp_code: str = message.text.replace('/', '')

            if not self._is_valid_totp_code(totp_code):
                self._handle_invalid_totp_code(message)
                return

            if session_manager.get_blocked_time(user_id) and datetime.now() < session_manager.get_blocked_time(user_id):
                self._handle_blocked_user(message)
                return

            attempts: int = session_manager.get_totp_attempts(user_id)
            if attempts > config.totp_max_attempts:
                self._handle_max_attempts_reached(message)
                return

            authenticator = TwoFactorAuthenticator(user_id, message.from_user.username)
            if authenticator.verify_totp_code(totp_code):
                session_manager.set_auth_state(user_id, session_manager.state_fabric.authenticated)
                session_manager.set_login_time(user_id)
                bot_logger.log("SUCCESS", f'TOTP code for user {user_id} verified.')
                self.bot.reply_to(message, 'TOTP code verified. Authentication successful.')
            else:
                session_manager.set_totp_attempts(user_id=user_id)
                bot_logger.error(f"Invalid TOTP code: {totp_code}")
                self.bot.reply_to(message, 'Invalid TOTP code. Please try again.')

    def _handle_blocked_user(self, message: Message) -> None:
        """
        Handle a blocked user.

        Args:
            message (telebot.types.Message): The message object received from the user.

        Returns:
            None
        """
        user_id = message.from_user.id
        bot_logger.error(f"User {user_id} is blocked")
        self.bot.reply_to(message, 'You are blocked. Please try again later.')

    def _send_totp_code_message(self, message: Message) -> None:
        """
        Sends a message to the user with a TOTP code.

        Args:
            message (telebot.types.Message): The message object received from the user.

        Returns:
            None
        """
        # Define emojis to be used in the message
        emojis = {
            'thought_balloon': self.emojis.get_emoji('thought_balloon'),
        }

        # Build the reply keyboard with the back keyboard type
        keyboard = self.keyboard.build_reply_keyboard(keyboard_type='back_keyboard')

        # Render the 'a_send_totp_code.jinja2' template with the user's name and emojis
        bot_answer = self.jinja.render_templates(
            'a_send_totp_code.jinja2',
            name=message.from_user.first_name or "Anonymous user",
            **emojis
        )

        # Send the message to the user with the reply markup and Markdown parse mode
        self.bot.send_message(message.chat.id, text=bot_answer, reply_markup=keyboard, parse_mode="Markdown")

    def _handle_invalid_totp_code(self, message: Message) -> None:
        """
        Handle the scenario when the user has entered an invalid TOTP code.

        This function logs an error, sends a reply message to the user, and increments the TOTP attempts.

        Args:
            message (telebot.types.Message): The message object received from the user.

        Returns:
            None
        """
        user_id = message.from_user.id
        bot_logger.error(f"Invalid TOTP code: {message.text}")
        self.bot.reply_to(message, 'Invalid TOTP code. Please enter a 6-digit code. For example, /123456.')
        session_manager.set_totp_attempts(user_id=user_id)

    def _handle_max_attempts_reached(self, message: Message) -> None:
        """
        Handle the scenario when the user has reached the maximum number of attempts.

        This function blocks the user and sends a reply message to the user.

        Args:
            message (Message): The message object received from the user.

        Returns:
            None
        """
        # Get the user ID from the message object
        user_id = message.from_user.id

        # Block the user
        self._block_user(user_id)

        # Send a reply message to the user
        self.bot.reply_to(message, 'You have reached the maximum number of attempts. Please try again later.')

    @staticmethod
    def _block_user(user_id: int) -> None:
        """
        Blocks a user by setting their authentication state to 'blocked', resetting their TOTP attempts,
        and setting a blocked time.

        Args:
            user_id (int): The ID of the user to block.

        Returns:
            None
        """
        # Set the user's authentication state to 'blocked'
        session_manager.set_auth_state(user_id, session_manager.state_fabric.blocked)
        # Reset the user's TOTP attempts
        session_manager.reset_totp_attempts(user_id)
        # Set a blocked time for the user
        session_manager.set_blocked_time(user_id)

    @staticmethod
    def _is_valid_totp_code(totp_code: str) -> bool:
        """
        Checks if the provided TOTP code is valid.

        A valid TOTP code is a 6-digit number.

        Args:
            totp_code (str): The TOTP code to check.

        Returns:
            bool: True if the TOTP code is valid, False otherwise.
        """
        return len(totp_code) == 6 and totp_code.isdigit()
