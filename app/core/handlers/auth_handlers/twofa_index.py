#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot.types import Message

from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_handler_session, bot_logger
from app.utilities.totp import TwoFactorAuthenticator


class TwoFAHandler(HandlerConstructor):
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
            msg = self.bot.send_message(message.chat.id, text=bot_answer, reply_markup=keyboard)

            self.bot.register_next_step_handler(msg, handle_code_verification)

            self.bot.enable_save_next_step_handlers(delay=2)

            self.bot.load_next_step_handlers()

        def handle_code_verification(message: Message):
            msg = self.bot.send_message(message.chat.id, text="Enter 2FA code:")
            self.bot.register_next_step_handler(msg, processing_code)

        def processing_code(message: Message):
            bot_logger.debug("Processing TOTP code in progress...")
            user_id = message.from_user.id
            user_name = message.from_user.username
            auth_code = message.text.replace('/', '')
            print(auth_code)
            if not auth_code:
                msg = self.bot.reply_to(message, 'Code should be a valid number. Please try again...')
                self.bot.register_next_step_handler(msg, processing_code)
                return
            authenticator = TwoFactorAuthenticator(message.from_user.id, message.from_user.username)
            code_is_verified = authenticator.verify_totp_code(auth_code)

            if code_is_verified:
                msg = self.bot.reply_to(message, 'Done processing TOTP code. Thank you!')
                self.bot.register_next_step_handler(msg, totp_code_verified)
            else:
                msg = self.bot.reply_to(message, 'Wrong TOTP code. Please try again...')
                self.bot.register_next_step_handler(msg, processing_code)

        def totp_code_verified(message: Message):
            bot_answer = self.jinja.render_templates('a_totp_code_verified.jinja2',
                                                     name=message.from_user.first_name)
            return self.bot.reply_to(message, text=bot_answer)

        self.bot.enable_save_next_step_handlers(delay=2)

        self.bot.load_next_step_handlers()
