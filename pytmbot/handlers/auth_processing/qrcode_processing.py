#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import Message

from pytmbot import exceptions
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import get_emoji_converter, get_keyboards
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler
from pytmbot.utils.message_deletion import (
    DeletionResult,
    DeletionStatus,
    deletion_manager,
)
from pytmbot.utils.totp import TwoFactorAuthenticator

logger = Logger()
em = get_emoji_converter()
keyboards = get_keyboards()


def _qr_deletion_callback(result: DeletionResult) -> None:
    """
    Callback function executed after QR code message deletion attempt.

    Args:
        result: Result of the deletion operation
    """
    if result.status == DeletionStatus.SUCCESS:
        logger.info("bot.handler.auth_processing.qrcode_processing.qr.code.ok")
    elif result.status == DeletionStatus.FAILED:
        logger.warning("bot.handler.auth_processing.qrcode_processing.delete.qr.fail")


@logger.session_decorator
def handle_qr_code_message(
    message: Message, bot: TeleBot, auto_delete_delay: int = 60
) -> Message | None:
    """
    Handles the QR code message by generating a TOTP QR code and sending it as a photo to the user.

    The QR code message is automatically deleted after the specified delay for security reasons.

    Args:
        message (Message): The message object received from the user.
        bot (TeleBot): The TeleBot instance used to send the QR code.
        auto_delete_delay (int): Delay in seconds before auto-deletion (default: 60)

    Returns:
        Optional[Message]: The message object sent to the user, or None if the QR code generation fails.

    Security Considerations:
        - QR code messages are auto-deleted to protect sensitive TOTP information
        - Messages are sent with content protection and spoiler tags
        - Graceful handling when deletion limits are exceeded
        - All operations are logged for security monitoring
    """
    if message.from_user is None:
        bot.send_message(
            message.chat.id,
            "⚠️ Cannot identify user for QR generation.",
        )
        return None

    user_id = message.from_user.id
    username = message.from_user.username or ""
    keyboard = keyboards.build_reply_keyboard(keyboard_type="auth_processing_keyboard")
    authenticator = TwoFactorAuthenticator(user_id, username)

    try:
        # Send typing indicator for better UX
        bot.send_chat_action(message.chat.id, "upload_photo")

        qr_code = authenticator.generate_totp_qr_code()

        if qr_code:
            # Send QR code with security features
            sent_message = bot.send_photo(
                message.chat.id,
                photo=qr_code,
                reply_markup=keyboard,
                caption=f"🔐 The QR code is ready. Click on the image and scan it in your 2FA app. "
                f"This message will be automatically deleted in {auto_delete_delay} seconds for security.",
                protect_content=True,
                has_spoiler=True,
                show_caption_above_media=True,
            )

            # Schedule automatic deletion for security protection
            deletion_result = deletion_manager.schedule_deletion(
                bot=bot,
                chat_id=message.chat.id,
                message_id=sent_message.message_id,
                user_id=user_id,
                delay_seconds=auto_delete_delay,
                callback=_qr_deletion_callback,
            )

            # Handle different deletion scheduling outcomes
            if deletion_result.status == DeletionStatus.LIMIT_EXCEEDED:
                # Inform user about exceeded deletion limit
                warning_msg = (
                    "⚠️ <b>Security Notice:</b> Too many pending auto-deletions. "
                    "This QR code will not be automatically deleted.\n\n"
                    "<i>Please manually delete this message immediately after scanning for security!</i>"
                )

                bot.send_message(
                    chat_id=message.chat.id,
                    text=warning_msg,
                    parse_mode="HTML",
                    reply_to_message_id=sent_message.message_id,
                )

                logger.warning(
                    "bot.handler.auth_processing.qrcode_processing.qr.code.warn"
                )

            elif deletion_result.status == DeletionStatus.SCHEDULED:
                logger.info(
                    "bot.handler.auth_processing.qrcode_processing.qr.code.info"
                )

            else:
                # Fallback for any other unexpected status
                logger.error(
                    "bot.handler.auth_processing.qrcode_processing.unexpected.deletion.fail"
                )

            return sent_message

        else:
            # Handle QR code generation failure
            emojis = {
                "thought_balloon": em.get_emoji("thought_balloon"),
                "anxious_face_with_sweat": em.get_emoji("anxious_face_with_sweat"),
            }

            response = Compiler.quick_render(
                template_name="b_none.jinja2",
                context="Failed to generate QR code... I apologize!",
                **emojis,
            )

            error_message = bot.send_message(message.chat.id, text=response)

            # Schedule deletion of error message as well (shorter delay)
            deletion_manager.schedule_deletion(
                bot=bot,
                chat_id=message.chat.id,
                message_id=error_message.message_id,
                user_id=user_id,
                delay_seconds=15,  # Delete error messages faster
                callback=_qr_deletion_callback,
            )

            logger.error(
                "bot.handler.auth_processing.qrcode_processing.generate.qr.fail",
                extra={"user_id": user_id, "chat_id": message.chat.id},
            )

            return None

    except Exception as error:
        # Send user-friendly error message
        error_msg = "⚠️ An error occurred while processing the QR code request."
        error_message = bot.send_message(message.chat.id, error_msg)

        # Schedule deletion of error message
        try:
            deletion_manager.schedule_deletion(
                bot=bot,
                chat_id=message.chat.id,
                message_id=error_message.message_id,
                user_id=user_id,
                delay_seconds=15,
                callback=_qr_deletion_callback,
            )
        except Exception:
            logger.error(
                "bot.handler.auth_processing.qrcode_processing.schedule.deletion.fail"
            )

        # Log detailed error information and raise custom exception
        error_context = ErrorContext(
            message="Failed handling QR code generation",
            error_code="HAND_021",
            metadata={
                "exception": str(error),
                "exception_type": type(error).__name__,
                "user_id": message.from_user.id if message.from_user else None,
                "chat_id": message.chat.id if message.chat else None,
                "command": "qr_code",
                "auto_delete_delay": auto_delete_delay,
            },
        )

        logger.error("bot.handler.auth_processing.qrcode_processing.qr.code.fail")
        raise exceptions.HandlingException(error_context)
