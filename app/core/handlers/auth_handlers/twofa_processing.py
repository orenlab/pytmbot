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
            """
            Handle the 'Enter 2FA code' message.

            This function builds a keyboard with options for QR code or entering 2FA code. It then renders a
            template with the user's name and sends it to the user.

            Parameters:
            - message: A Message object containing information about the message.

            """
            try:
                user_id = message.from_user.id
                if session_manager.is_blocked(user_id):
                    bot_logger.error(f"User {message.from_user.id} blocked, an can't enter 2FA code")
                    self.bot.send_message(message.chat.id,
                                          text="⛔⛔⛔The two-factor authentication code has been entered "
                                               "incorrectly several times. It may be necessary to pause for a few "
                                               "minutes, typically no more than five, and then try again.🤦‍")
                    return
                session_manager.set_auth_state(user_id, 'processing')
                print(session_manager.user_data)
                # Build inline keyboard with options for QR code or entering 2FA code
                emojis = {
                    'thought_balloon': self.emojis.get_emoji('thought_balloon'),
                }
                keyboard = self.keyboard.build_reply_keyboard(keyboard_type='back_keyboard')
                bot_answer = self.jinja.render_templates(
                    'a_send_totp_code.jinja2',
                    name=message.from_user.first_name or "Anonymous user",
                    **emojis
                )
                self.bot.send_message(message.chat.id, text=bot_answer, reply_markup=keyboard, parse_mode="Markdown")
            except Exception as err:
                bot_logger.error(err, exc_info=True)

        @self.bot.message_handler(regexp=r"[0-9]{6}$",
                                  func=lambda message:
                                  message.from_user.id in config.allowed_admins_ids and session_manager.get_auth_state(
                                      message.from_user.id) == 'processing')
        @logged_handler_session
        def handle_totp_code_verification(message: Message):
            """
            Handle TOTP code verification.

            This function verifies the TOTP code sent by the user and updates the attempt count and reset time
            accordingly.

            Args:
            - message (Message): The message object containing the TOTP code.

            Raises:
            - PyTeleMonBotHandlerError: If an exception occurs during the verification process.
            """
            user_id = message.from_user.id
            totp_code = message.text.replace('/', '')

            if not (len(totp_code) == 6 and totp_code.isdigit()):
                bot_logger.error(f"Invalid TOTP code: {totp_code}")
                self.bot.reply_to(message, 'Invalid TOTP code. Please enter a 6-digit code. For example, /123456.')
                session_manager.set_totp_attempts(user_id=user_id)
                return

            if session_manager.get_blocked_time(user_id) and datetime.now() < session_manager.get_blocked_time(user_id):
                bot_logger.error(f"User {user_id} is blocked")
                self.bot.reply_to(message, 'You are blocked. Please try again later.')
                return

            attempts = session_manager.get_totp_attempts(user_id)
            if attempts > config.totp_max_attempts:
                session_manager.set_auth_state(user_id, 'blocked')
                session_manager.reset_totp_attempts(user_id)
                session_manager.set_blocked_time(user_id)
                bot_logger.error(f"Reached max TOTP attempts for user {user_id}")
                self.bot.reply_to(message, 'You have reached the maximum number of attempts. Please try again later.')
                return

            authenticator = TwoFactorAuthenticator(user_id, message.from_user.username)
            if authenticator.verify_totp_code(totp_code):
                session_manager.set_auth_state(user_id, 'authenticated')
                session_manager.set_login_time(user_id)
                bot_logger.log("SUCCESS", f'TOTP code for user {user_id} verified.')
                self.bot.reply_to(message, 'TOTP code verified. Authentication successful.')
            else:
                session_manager.set_totp_attempts(user_id=user_id)
                bot_logger.error(f"Invalid TOTP code: {totp_code}")
                self.bot.reply_to(message, 'Invalid TOTP code. Please try again.')
