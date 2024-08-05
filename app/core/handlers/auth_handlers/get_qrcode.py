#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot.types import Message

from app.core.handlers.handler import HandlerConstructor
from app.core.logs import logged_handler_session
from app.utilities.totp import TOTPGenerator


class GetQrcodeHandler(HandlerConstructor):
    """Class to handle auth required messages."""

    def handle(self) -> None:
        allowed_admins_ids = set(self.config.allowed_admins_ids)

        @self.bot.message_handler(regexp='Get QR-code for 2FA app',
                                  func=lambda message: message.from_user.id in allowed_admins_ids)
        @self.bot.message_handler(commands=['qrcode'], func=lambda message: message.from_user.id in allowed_admins_ids)
        @logged_handler_session
        def handle_qrcode_message(message: Message):
            # Build inline keyboard with options for QR code or entering 2FA code
            keyboard = self.keyboard.build_reply_keyboard(keyboard_type='auth_processing_keyboard')

            with TOTPGenerator(message.from_user.id, message.from_user.first_name) as generator:
                bot_answer = generator.generate_totp_qr_code()

            # Send message to user with appropriate reply markup
            if bot_answer:
                self.bot.send_photo(
                    message.chat.id,
                    photo=bot_answer,
                    reply_markup=keyboard,
                    caption="The QR code is ready. Click on the image and scan it in your 2FA app",
                    protect_content=True,
                    has_spoiler=True,
                    show_caption_above_media=True
                )
            else:
                emojis = {
                    'thought_balloon': self.emojis.get_emoji('thought_balloon'),
                    'anxious_face_with_sweat': self.emojis.get_emoji('anxious_face_with_sweat'),
                }
                error_answer = self.jinja.render_templates('none.jinja2',
                                                           context="Failed to generate QR code... I apologize!",
                                                           **emojis)
                self.bot.send_message(message.chat.id, text="Failed to generate QR code", reply_markup=error_answer)
