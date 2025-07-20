#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from typing import Optional

from telebot import TeleBot
from telebot.types import LinkPreviewOptions, Message

from pytmbot import exceptions
from pytmbot.exceptions import ErrorContext
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler
from pytmbot.utils.message_deletion import (
    deletion_manager,
    DeletionResult,
    DeletionStatus,
)

logger = Logger()


def _deletion_callback(result: DeletionResult) -> None:
    """
    Callback function executed after deletion attempt.

    Args:
        result: Result of the deletion operation
    """
    if result.status == DeletionStatus.SUCCESS:
        logger.debug(
            f"Message {result.message_id} successfully deleted for user {result.user_id}"
        )
    elif result.status == DeletionStatus.FAILED:
        logger.warning(
            f"Failed to delete message {result.message_id} for user {result.user_id}: "
            f"{result.error_message}"
        )


@logger.session_decorator
def handle_getmyid(
    message: Message, bot: TeleBot, auto_delete_delay: int = 30
) -> Optional[Message]:
    """
    Handler for /getmyid command - returns user and chat ID information
    for initial bot configuration and debugging purposes.

    The response message is automatically deleted after the specified delay
    to maintain privacy and confidentiality of sensitive information.

    Args:
        message: The incoming Telegram message
        bot: TeleBot instance for sending responses
        auto_delete_delay: Delay in seconds before auto-deletion (default: 30)

    Returns:
        The sent message object, or None if sending failed

    Security Considerations:
        - Messages containing sensitive ID information are auto-deleted
        - Per-user limits prevent resource exhaustion attacks
        - Graceful handling when deletion limits are exceeded
        - All operations are logged for security monitoring
    """
    try:
        # Send typing indicator for better UX
        bot.send_chat_action(message.chat.id, "typing")

        # Extract user and chat information
        user_id = message.from_user.id
        chat_id = message.chat.id
        first_name = message.from_user.first_name or "Unknown"
        last_name = message.from_user.last_name or ""
        username = message.from_user.username
        chat_type = message.chat.type
        chat_title = getattr(message.chat, "title", None)

        # Map chat type to human-readable format
        chat_type_display = {
            "private": "Private Chat",
            "group": "Group",
            "supergroup": "Supergroup",
            "channel": "Channel",
        }.get(chat_type, chat_type.title())

        # Check if user is bot administrator
        is_bot_admin = message.from_user.id in getattr(bot, "admin_ids", [])

        # Generate response using template compiler
        with Compiler(
            template_name="b_getmyid.jinja2",
            user_id=user_id,
            chat_id=chat_id,
            first_name=first_name,
            last_name=last_name,
            username=username,
            chat_type=chat_type_display,
            chat_title=chat_title,
            command="getmyid",
            is_bot_admin=is_bot_admin,
        ) as compiler:
            answer = compiler.compile()

        # Send the response message
        sent_message = bot.send_message(
            chat_id=chat_id,
            text=answer,
            parse_mode="HTML",
            link_preview_options=LinkPreviewOptions(is_disabled=True),
        )

        # Schedule automatic deletion for privacy protection
        deletion_result = deletion_manager.schedule_deletion(
            bot=bot,
            chat_id=chat_id,
            message_id=sent_message.message_id,
            user_id=user_id,
            delay_seconds=auto_delete_delay,
            callback=_deletion_callback,
        )

        # Handle different deletion scheduling outcomes
        if deletion_result.status == DeletionStatus.LIMIT_EXCEEDED:
            # Inform user about exceeded deletion limit
            warning_msg = (
                "⚠️ <b>Privacy Notice:</b> Too many pending auto-deletions. "
                "This message will not be automatically deleted.\n\n"
                "<i>Please manually delete this message for privacy.</i>"
            )

            bot.send_message(
                chat_id=chat_id,
                text=warning_msg,
                parse_mode="HTML",
                reply_to_message_id=sent_message.message_id,
            )

            logger.warning(f"Auto-deletion limit exceeded for user {user_id}. ")

        elif deletion_result.status == DeletionStatus.SCHEDULED:
            logger.info(
                f"Auto-deletion scheduled for message {sent_message.message_id} "
                f"(user {user_id}) in {auto_delete_delay} seconds. "
            )

        else:
            # Fallback for any other unexpected status
            logger.error(f"Unexpected deletion result status: {deletion_result.status}")

        return sent_message

    except Exception as error:
        # Send user-friendly error message
        error_msg = "⚠️ An error occurred while retrieving ID information."
        bot.send_message(message.chat.id, error_msg)

        # Log detailed error information and raise custom exception
        error_context = ErrorContext(
            message="Failed handling the getmyid command",
            error_code="HAND_015",
            metadata={
                "exception": str(error),
                "exception_type": type(error).__name__,
                "user_id": message.from_user.id if message.from_user else None,
                "chat_id": message.chat.id if message.chat else None,
                "command": "getmyid",
                "auto_delete_delay": auto_delete_delay,
            },
        )

        logger.error(f"Handler error: {error_context}")
        raise exceptions.HandlingException(error_context)
