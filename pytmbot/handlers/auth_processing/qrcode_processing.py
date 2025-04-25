#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import threading
from typing import Optional

from telebot import TeleBot
from telebot.types import Message

from pytmbot import exceptions
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import keyboards, em
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler
from pytmbot.utils.totp import TwoFactorAuthenticator

logger = Logger()


@logger.session_decorator
def handle_qr_code_message(message: Message, bot: TeleBot) -> Optional[Message]:
    """
    Handles the QR code message by generating a TOTP QR code and sending it as a photo to the user.

    Args:
        message (Message): The message object received from the user.
        bot (TeleBot): The TeleBot instance used to send the QR code.

    Returns:
        Optional[Message]: The message object sent to the user, or None if the QR code generation fails.
    """
    keyboard = keyboards.build_reply_keyboard(keyboard_type="auth_processing_keyboard")
    authenticator = TwoFactorAuthenticator(
        message.from_user.id, message.from_user.username
    )
    qr_code = authenticator.generate_totp_qr_code()

    try:

        if qr_code:
            msg = bot.send_photo(
                message.chat.id,
                photo=qr_code,
                reply_markup=keyboard,
                caption="The QR code is ready. Click on the image and scan it in your 2FA app. "
                        "After 60 seconds it will be deleted for security reasons.",
                protect_content=True,
                has_spoiler=True,
                show_caption_above_media=True,
            )

            def delete_qr_code():
                bot.delete_message(message.chat.id, msg.message_id)

            try:
                threading.Timer(60, delete_qr_code).start()
            except Exception as err:
                logger.error(
                    f"Error deleting QR code: {err}. Deleting manually for security reasons."
                )
                bot.send_message(
                    message.chat.id,
                    text="Failed to delete QR code. Deleting manually for security reasons.",
                )
                return

        else:
            emojis = {
                "thought_balloon": em.get_emoji("thought_balloon"),
                "anxious_face_with_sweat": em.get_emoji("anxious_face_with_sweat"),
            }

            with Compiler(
                    template_name="b_none.jinja2",
                    context="Failed to generate QR code... I apologize!",
                    **emojis,
            ) as compiler:
                response = compiler.compile()

            bot.send_message(message.chat.id, text=response)

    except Exception as error:
        bot.send_message(
            message.chat.id, "⚠️ An error occurred while processing the plugins command."
        )
        raise exceptions.HandlingException(ErrorContext(
            message="Failed handling QR code",
            error_code="HAND_021",
            metadata={"exception": str(error)}
        ))
