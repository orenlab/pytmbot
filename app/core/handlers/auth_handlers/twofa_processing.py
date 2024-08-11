#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
import datetime
from typing import Type

from telebot.types import Message

from app import bot_logger, config
from app.core.auth_processing import SessionManager
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
        session_manager = SessionManager(int, str, datetime, Type[int])

        @bot_logger.catch()
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
            auth_data = session_manager._make([message.from_user.id, 'processing', None, None])
            print(auth_data)
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

        @self.bot.message_handler(regexp=r"[0-9]{6}$",
                                  func=lambda message:
                                  message.from_user.id in config.allowed_admins_ids)
        @logged_handler_session
        @bot_logger.catch()
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
            try:
                user_id = message.from_user.id

                #    if auth_data.is_blocked() or auth_data.get_totp_attempts() >= config.totp_max_attempts:
                #        self.bot.reply_to(message,
                #                          'You have reached the maximum number of attempts. Please try again later.')
                #        return

                totp_code = message.text.replace('/', '')
                authenticator = TwoFactorAuthenticator(user_id, message.from_user.username)

                if authenticator.verify_totp_code(totp_code):
                    auth_data = session_manager._make([user_id, 'authorized', datetime.datetime.now(), None])
                    print(auth_data)
                    self.bot.reply_to(message, 'TOTP code verified successfully.')
                else:
                    attempts = repr(session_manager.totp_attempts)
                    auth_data = session_manager._make([user_id, 'processing', None, int(attempts) + 1 if attempts else 1])
                    print(auth_data)
                    self.bot.reply_to(message, 'Invalid TOTP code. Please try again.')

            except Exception as e:
                raise self.exceptions.PyTeleMonBotHandlerError(f"Failed at @{__name__}: {str(e)}")
