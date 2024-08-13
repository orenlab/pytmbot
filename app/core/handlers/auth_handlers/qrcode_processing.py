#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
import threading

from telebot.types import Message

from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_handler_session, bot_logger
from app.utilities.totp import TwoFactorAuthenticator


class GetQrcodeHandler(HandlerConstructor):
    """Class to handle auth required messages."""

    def handle(self) -> None:

        # Define the set of allowed admin IDs
        allowed_admin_ids = set(self.config.allowed_admins_ids)

        # Define a message handler for the 'Get QR-code for 2FA app' message and the 'qrcode' command
        @self.bot.message_handler(regexp='Get QR-code for 2FA app',
                                  func=lambda message: message.from_user.id in allowed_admin_ids)
        @self.bot.message_handler(commands=['qrcode'], func=lambda message: message.from_user.id in allowed_admin_ids)
        @logged_handler_session
        def handle_qrcode_message(message: Message):
            """
            Handle the 'Get QR-code for 2FA app' message or the 'qrcode' command.

            Args:
                message (Message): The message object received from the user.

            Returns:
                None
            """

            # Build the reply keyboard with the auth_processing_keyboard type
            keyboard = self.keyboard.build_reply_keyboard(keyboard_type='auth_processing_keyboard')

            # Create an instance of the TwoFactorAuthenticator class
            authenticator = TwoFactorAuthenticator(message.from_user.id, message.from_user.username)

            # Generate the QR code for 2FA authentication
            qr_code = authenticator.generate_totp_qr_code()

            # Check if the QR code was generated successfully
            if qr_code:
                # Send the QR code to the user with a caption and reply markup
                msg = self.bot.send_photo(
                    message.chat.id,
                    photo=qr_code,
                    reply_markup=keyboard,
                    caption="The QR code is ready. Click on the image and scan it in your 2FA app. "
                            "After 60 seconds it will be deleted for security reasons.",
                    protect_content=True,
                    has_spoiler=True,
                    show_caption_above_media=True
                )

                # Define a function to delete the QR code message after 60 seconds
                def delete_qr_code():
                    self.bot.delete_message(message.chat.id, msg.message_id)

                try:
                    # Start a timer to delete the QR code message after 60 seconds in thread
                    threading.Timer(60, delete_qr_code).start()
                except Exception as err:
                    bot_logger.error(f"Error deleting QR code: {err}. Deleting manually for security reasons.")
                    # Send a message to the user if the timer fails to start
                    self.bot.send_message(message.chat.id,
                                          text="Failed to delete QR code. Deleting manually for security reasons.")
                    return

            else:
                emojis = {
                    'thought_balloon': self.emojis.get_emoji('thought_balloon'),
                    'anxious_face_with_sweat': self.emojis.get_emoji('anxious_face_with_sweat'),
                }

                error_answer = self.jinja.render_templates('b_none.jinja2',
                                                           context="Failed to generate QR code... I apologize!",
                                                           **emojis)

                self.bot.send_message(message.chat.id, text=error_answer)
