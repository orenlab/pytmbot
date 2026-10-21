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
from pytmbot.handlers.auth_processing.auth_processing import (
    is_private_chat,
    send_private_chat_notice,
)
from pytmbot.handlers.handlers_util.utils import send_bot_message, send_main_message
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler
from pytmbot.utils.message_deletion import (
    DeletionResult,
    DeletionStatus,
    create_post_delete_navigation_callback,
    deletion_manager,
)
from pytmbot.utils.totp import TwoFactorAuthenticator

logger = Logger()
em = get_emoji_converter()
keyboards = get_keyboards()
QR_UNAVAILABLE_TEXT = (
    "⚠️ Couldn't create the QR code: the bot's 2FA settings are incomplete. "
    "Ask the bot administrator to check the bot logs."
)
QR_DELETED_NAVIGATION_TEXT = (
    "🧹 QR code message was deleted for security.\n"
    "Use the button below to return to the main menu."
)
QR_DELETION_BUSY_TEXT = (
    "⏳ Too many messages are waiting for auto-deletion. Please try again in a minute."
)
QR_NOT_SCHEDULED_TEXT = (
    "⚠️ Couldn't schedule the QR code for auto-deletion, so I removed it. "
    "Please try again in a minute."
)
QR_NOT_REMOVED_TEXT = (
    "⚠️ Couldn't schedule the QR code for auto-deletion or remove it. "
    "Delete the QR code message yourself right after scanning it."
)


def _qr_deletion_callback(
    result: DeletionResult,
) -> None:
    """
    Callback function executed after QR code message deletion attempt.

    Args:
        result: Result of the deletion operation
    """
    if result.status == DeletionStatus.SUCCESS:
        logger.info("bot.handler.auth_processing.qrcode_processing.qr.code.ok")
    elif result.status == DeletionStatus.FAILED:
        logger.warning("bot.handler.auth_processing.qrcode_processing.delete.qr.fail")


def _schedule_qr_deletion(
    bot: TeleBot,
    *,
    chat_id: int,
    message_id: int,
    user_id: int,
    delay_seconds: int,
) -> bool:
    """Schedule the auto-deletion of a QR message; return True when scheduled."""
    try:
        deletion_result = deletion_manager.schedule_deletion(
            bot=bot,
            chat_id=chat_id,
            message_id=message_id,
            user_id=user_id,
            delay_seconds=delay_seconds,
            callback=create_post_delete_navigation_callback(
                _qr_deletion_callback,
                bot=bot,
                chat_id=chat_id,
                navigation_text=QR_DELETED_NAVIGATION_TEXT,
            ),
        )
    except Exception as error:
        logger.error(
            "bot.handler.auth_processing.qrcode_processing.schedule.deletion.fail",
            error=str(error),
        )
        return False

    if deletion_result.status != DeletionStatus.SCHEDULED:
        # LIMIT_EXCEEDED (another deletion took the last slot) or a failure.
        logger.error(
            "bot.handler.auth_processing.qrcode_processing.unexpected.deletion.fail",
            status=deletion_result.status.name,
        )
        return False

    logger.info("bot.handler.auth_processing.qrcode_processing.qr.code.info")
    return True


def _withdraw_qr_message(bot: TeleBot, chat_id: int, message_id: int) -> bool:
    """Delete a QR message whose auto-deletion is not scheduled; True if deleted."""
    try:
        bot.delete_message(chat_id, message_id)
    except Exception as error:
        logger.error(
            "bot.handler.auth_processing.qrcode_processing.withdraw.qr.fail",
            error=str(error),
        )
        return False
    return True


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
        Message | None: The message object sent to the user, or None if no QR
        code was left in the chat.

    Security Considerations:
        - QR codes are sent only in a private chat; groups get a link to it
        - QR code messages are auto-deleted to protect sensitive TOTP information
        - Messages are sent with content protection and spoiler tags
        - A QR code is never left without scheduled deletion: it is refused when
          the deletion limit is reached and removed when scheduling fails
        - All operations are logged for security monitoring
    """
    if message.from_user is None:
        send_main_message(
            bot,
            message.chat.id,
            "⚠️ Cannot identify user for QR generation.",
        )
        return None

    if not is_private_chat(message.chat):
        send_private_chat_notice(bot, message)
        return None

    user_id = message.from_user.id
    keyboard = keyboards.build_reply_keyboard(keyboard_type="auth_processing_keyboard")
    try:
        # Users without a Telegram username get an id-derived secret.
        authenticator = TwoFactorAuthenticator(user_id, message.from_user.username)
    except exceptions.TOTPError as error:
        logger.error(
            "bot.handler.auth_processing.qrcode_processing.totp.unavailable.fail",
            error=error.sanitized_message(),
        )
        send_bot_message(
            bot,
            message.chat.id,
            text=QR_UNAVAILABLE_TEXT,
            reply_markup=keyboard,
        )
        return None

    if not deletion_manager.can_schedule(user_id):
        logger.warning(
            "bot.handler.auth_processing.qrcode_processing.deletion.limit.warn"
        )
        send_bot_message(
            bot,
            message.chat.id,
            text=QR_DELETION_BUSY_TEXT,
            reply_markup=keyboard,
        )
        return None

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

            if _schedule_qr_deletion(
                bot,
                chat_id=message.chat.id,
                message_id=sent_message.message_id,
                user_id=user_id,
                delay_seconds=auto_delete_delay,
            ):
                return sent_message

            # Never leave the QR code (it holds the 2FA secret) in the chat.
            if _withdraw_qr_message(bot, message.chat.id, sent_message.message_id):
                send_bot_message(
                    bot,
                    message.chat.id,
                    text=QR_NOT_SCHEDULED_TEXT,
                    reply_markup=keyboard,
                )
                return None
            # Never claim the QR code is gone while it is still in the chat.
            send_bot_message(
                bot,
                message.chat.id,
                text=QR_NOT_REMOVED_TEXT,
                reply_markup=keyboard,
                reply_to_message_id=sent_message.message_id,
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
                context="Couldn't generate a QR code right now. Please try again.",
                **emojis,
            )

            error_message = send_bot_message(
                bot,
                message.chat.id,
                text=response,
                reply_markup=keyboard,
            )

            # Schedule deletion of error message as well (shorter delay)
            deletion_manager.schedule_deletion(
                bot=bot,
                chat_id=message.chat.id,
                message_id=error_message.message_id,
                user_id=user_id,
                delay_seconds=15,  # Delete error messages faster
                callback=create_post_delete_navigation_callback(
                    _qr_deletion_callback,
                    bot=bot,
                    chat_id=message.chat.id,
                    navigation_text=QR_DELETED_NAVIGATION_TEXT,
                ),
            )

            logger.error(
                "bot.handler.auth_processing.qrcode_processing.generate.qr.fail",
                extra={"user_id": user_id, "chat_id": message.chat.id},
            )

            return None

    except Exception as error:
        # Send user-friendly error message
        error_msg = "⚠️ Couldn't create the QR code right now. Please try again."
        error_message = send_bot_message(
            bot,
            message.chat.id,
            text=error_msg,
            reply_markup=keyboard,
        )

        # Schedule deletion of error message
        try:
            deletion_manager.schedule_deletion(
                bot=bot,
                chat_id=message.chat.id,
                message_id=error_message.message_id,
                user_id=user_id,
                delay_seconds=15,
                callback=create_post_delete_navigation_callback(
                    _qr_deletion_callback,
                    bot=bot,
                    chat_id=message.chat.id,
                    navigation_text=QR_DELETED_NAVIGATION_TEXT,
                ),
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
        raise exceptions.HandlingException(error_context) from error
