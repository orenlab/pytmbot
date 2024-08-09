#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import time
from dataclasses import dataclass, field

from telebot.types import Message

from app import bot_logger
from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_handler_session
from app.utilities.totp import TwoFactorAuthenticator


@dataclass
class Users:
    user_data: dict = field(default_factory=dict)


class TwoFAStartHandler(HandlerConstructor):
    """Class to handle auth required messages."""

    @staticmethod
    def get_attempt_count(user_id):
        return Users.user_data.get(user_id, {}).get('attempt_count', 0)

    @staticmethod
    def set_attempt_count(user_id, count):
        user_data = Users.user_data.setdefault(user_id, {})
        user_data['attempt_count'] = count

    @staticmethod
    def get_attempt_reset_time(user_id):
        return Users.user_data.get(user_id, {}).get('attempt_reset_time', 0)

    @staticmethod
    def set_attempt_reset_time(user_id, _time):
        user_data = Users.user_data.setdefault(user_id, {})
        user_data['attempt_reset_time'] = _time

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
        @bot_logger.catch()
        @logged_handler_session
        def handle_twofa_message(message: Message):
            """
            Handle the 'Enter 2FA code' message.

            This function builds a keyboard with options for QR code or entering 2FA code. It then renders a
            template with the user's name and sends it to the user.

            Parameters:
            - message: A Message object containing information about the message.

            """
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

        @self.bot.message_handler(regexp="^d{6}$")
        @logged_handler_session
        def handle_code_verification(message: Message):
            try:
                print(message.text)
                bot_logger.info(f"Start processing TOTP code for user {message.from_user.username}...")
                auth_code = message.text.split(':', 1)[-1].strip()
                if not auth_code.isdigit():
                    bot_logger.debug(f"TOTP code for user {message.from_user.username} is invalid.")
                    self.bot.reply_to(message, 'Code should be a valid number. Please try again... Format: code:222222')
                    return

                authenticator = TwoFactorAuthenticator(message.from_user.id, message.from_user.username)

                code_is_verified = authenticator.verify_totp_code(auth_code)

                if code_is_verified:
                    bot_logger.success(f"Done processing TOTP code for user {message.from_user.username}.")
                    self.bot.reply_to(message, 'Done processing TOTP code. Thank you!')
                else:
                    user_id = message.from_user.id
                    last_reset_time = self.get_attempt_reset_time(user_id)
                    if last_reset_time is None or time.time() >= last_reset_time + 300:
                        self.set_attempt_reset_time(user_id, time.time() + 300)
                        self.set_attempt_count(user_id, 1)
                    else:
                        self.set_attempt_count(user_id, self.get_attempt_count(user_id) + 1)

                    if self.get_attempt_count(user_id) > 3:
                        bot_logger.warning(
                            f"Exceeded the maximum number of attempts for user {message.from_user.username}.")
                        self.bot.reply_to(message, 'Too many attempts. Please try again later after 5 minutes.')
                    else:
                        bot_logger.error(
                            f"Failed to verify TOTP code for user {message.from_user.username}. "
                            f"Attempt {self.get_attempt_count(user_id)} of 3.")
                        self.bot.reply_to(message, 'Incorrect code. Please try again...')
            except Exception as e:
                raise self.exceptions.PyTeleMonBotHandlerError(f"Failed at @{__name__}: {str(e)}")
