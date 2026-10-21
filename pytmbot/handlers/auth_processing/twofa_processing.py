#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import threading
import time
from collections import deque
from collections.abc import Callable
from datetime import datetime
from typing import cast

from telebot import TeleBot
from telebot.types import (
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
    User,
)

from pytmbot import exceptions
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import (
    get_emoji_converter,
    get_keyboards,
    get_session_manager,
    settings,
    var_config,
)
from pytmbot.handlers.auth_processing.auth_processing import (
    is_private_chat,
    send_private_chat_notice,
)
from pytmbot.handlers.docker_handlers.callback_data import (
    post_auth_return_callback,
    post_auth_return_label,
)
from pytmbot.handlers.handlers_util.utils import (
    HANDLER_COMMAND_ERROR_MESSAGE,
    send_main_message,
    send_telegram_message,
)
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler
from pytmbot.utils import is_valid_totp_code
from pytmbot.utils.totp import TOTPVerificationResult, TwoFactorAuthenticator

logger = Logger()
em = get_emoji_converter()
keyboards = get_keyboards()
session_manager = get_session_manager()
allowed_admins_ids = set(settings.access_control.allowed_admins_ids)
_TOTP_RATE_LIMIT_WINDOW_SECONDS = 60.0
_TOTP_ATTEMPT_CACHE_COMPACT_THRESHOLD = 256
_totp_attempt_times: dict[int, deque[float]] = {}
_totp_attempt_lock = threading.RLock()
TOTP_UNAVAILABLE_TEXT = (
    "⚠️ 2FA can't be checked right now: the bot's 2FA settings are incomplete. "
    "Ask the bot administrator to check the bot logs."
)
TOTP_ISSUED_BEFORE_RESTART_TEXT = (
    "⏳ The bot restarted moments ago. For security, codes issued before the "
    "restart aren't accepted. Wait for the next code in your app (up to a minute)."
)


def _totp_rate_limit_threshold() -> int:
    """Compute burst limit for TOTP attempts inside a short window."""
    return max(5, int(var_config.totp_max_attempts) * 2)


def _prune_stale_totp_attempts(now: float, *, current_user_id: int) -> None:
    """Compact stale TOTP attempt buckets when the cache grows large."""
    if len(_totp_attempt_times) <= _TOTP_ATTEMPT_CACHE_COMPACT_THRESHOLD:
        return

    stale_user_ids: list[int] = []
    for tracked_user_id, tracked_attempts in _totp_attempt_times.items():
        if tracked_user_id == current_user_id:
            continue
        while (
            tracked_attempts
            and now - tracked_attempts[0] > _TOTP_RATE_LIMIT_WINDOW_SECONDS
        ):
            tracked_attempts.popleft()
        if not tracked_attempts:
            stale_user_ids.append(tracked_user_id)

    for stale_user_id in stale_user_ids:
        _totp_attempt_times.pop(stale_user_id, None)


def _consume_totp_attempt(user_id: int) -> bool:
    """
    Register TOTP attempt and return whether user exceeded burst limit.

    Returns:
        True when attempt should be rate-limited.
    """
    now = time.monotonic()
    with _totp_attempt_lock:
        attempts = _totp_attempt_times.setdefault(user_id, deque())
        while attempts and now - attempts[0] > _TOTP_RATE_LIMIT_WINDOW_SECONDS:
            attempts.popleft()

        if len(attempts) >= _totp_rate_limit_threshold():
            return True

        attempts.append(now)
        _prune_stale_totp_attempts(now, current_user_id=user_id)
        return False


def _extract_totp_code(raw_text: str | None) -> str:
    """
    Normalize possible TOTP input formats to a plain 6-digit code.

    Supported formats:
    - 123456
    - /123456
    - /123456@botname
    """
    if not raw_text:
        return ""

    text = raw_text.strip()
    if not text:
        return ""

    if text.startswith("/"):
        command_part = text[1:].split(maxsplit=1)[0]
        command_name = command_part.split("@", 1)[0]
        normalized_command = command_name.strip()
        if TwoFactorAuthenticator.TOTP_CODE_PATTERN.match(normalized_command):
            return normalized_command
        return ""

    return text


# regexp='Enter 2FA code'
@logger.session_decorator
def handle_twofa_message(message: Message, bot: TeleBot) -> None:
    """
    Handle the 'Enter 2FA code' message.

    Args:
        message (Message): The message object received from the user.
        bot (TeleBot): The TeleBot instance.

    Returns:
        None
    """
    if message.from_user is None:
        send_main_message(
            bot,
            message.chat.id,
            "⚠️ Cannot identify user for 2FA flow.",
        )
        return
    user_id = message.from_user.id
    try:
        if not is_private_chat(message.chat):
            send_private_chat_notice(bot, message)
            return

        if session_manager.is_blocked(user_id):
            _handle_blocked_user(message, bot)
            return

        session_manager.set_auth_state(user_id, session_manager.state_fabric.PROCESSING)

        _send_totp_code_message(message, bot)

    except Exception as error:
        send_main_message(
            bot,
            message.chat.id,
            HANDLER_COMMAND_ERROR_MESSAGE,
        )
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling the twofa command",
                error_code="HAND_020",
                metadata={"exception": str(error)},
            )
        ) from error


# regexp=r"[0-9]{6}$"
@logger.session_decorator
def handle_totp_code_verification(message: Message, bot: TeleBot) -> None:
    """
    Handle the verification of the TOTP code.

    Args:
        message (Message): The message object received from the user.
        bot (TeleBot): The TeleBot instance.

    Returns:
        None
    """

    def stop_if(should_stop: bool, action: Callable[[], object]) -> bool:
        if should_stop:
            action()
            return True
        return False

    if stop_if(
        message.from_user is None,
        lambda: send_main_message(
            bot,
            message.chat.id,
            "⚠️ Cannot identify user for TOTP verification.",
        ),
    ):
        return

    from_user = cast(User, message.from_user)
    user_id: int = from_user.id
    current_state = session_manager.get_auth_state(user_id)
    if stop_if(
        current_state != session_manager.state_fabric.PROCESSING,
        lambda: logger.debug(
            "bot.handler.auth_processing.twofa_processing.ignoring.totp.debug",
            user_id=user_id,
            auth_state=current_state,
        ),
    ):
        return

    if stop_if(
        not is_private_chat(message.chat),
        lambda: _reject_code_outside_private_chat(message, bot),
    ):
        return

    totp_code: str = _extract_totp_code(message.text)

    if stop_if(
        not is_valid_totp_code(totp_code),
        lambda: _handle_invalid_totp_code(message, bot),
    ):
        return

    blocked_until = session_manager.get_blocked_time(user_id)
    attempts = session_manager.get_totp_attempts(user_id)
    attempt_guards = (
        (
            blocked_until is not None and datetime.now() < blocked_until,
            lambda: _handle_blocked_user(message, bot),
        ),
        (
            _consume_totp_attempt(user_id),
            lambda: _handle_rate_limited_totp_attempt(message, bot),
        ),
        (
            attempts >= var_config.totp_max_attempts,
            lambda: _handle_max_attempts_reached(message, bot),
        ),
    )
    for should_stop, action in attempt_guards:
        if stop_if(should_stop, action):
            return None

    verification = _verify_totp_code(message, bot, from_user, totp_code)
    if verification is None:
        return None
    if verification is TOTPVerificationResult.VALID:
        _complete_authentication(message, bot, user_id)
    elif verification is TOTPVerificationResult.ISSUED_BEFORE_RESTART:
        # Not the user's mistake: no failed attempt is counted.
        logger.warning(
            "bot.handler.auth_processing.twofa_processing.totp.before.restart.warn",
            user_id=user_id,
        )
        bot.reply_to(message, TOTP_ISSUED_BEFORE_RESTART_TEXT)
    else:
        session_manager.increment_totp_attempts(user_id=user_id)
        logger.error("bot.handler.auth_processing.twofa_processing.invalid.totp.fail")
        bot.reply_to(message, "That 2FA code is invalid. Please try again.")
    return None


def _reject_code_outside_private_chat(message: Message, bot: TeleBot) -> None:
    """
    Remove a 2FA code sent to a group and point the user to the private chat.

    The code is not checked and does not count as an attempt.
    """
    logger.warning(
        "bot.handler.auth_processing.twofa_processing.group.code.deny",
        user_id=message.from_user.id if message.from_user else None,
    )
    try:
        bot.delete_message(message.chat.id, message.message_id)
    except Exception as error:
        # The bot may lack the right to delete members' messages.
        logger.warning(
            "bot.handler.auth_processing.twofa_processing.group.code.delete.fail",
            error=str(error),
        )
    send_private_chat_notice(bot, message)


def _verify_totp_code(
    message: Message, bot: TeleBot, user: User, totp_code: str
) -> TOTPVerificationResult | None:
    """
    Verify a TOTP code for the user.

    Users without a Telegram username are supported (the secret is derived
    from their user id). Returns ``None`` after telling the user when 2FA
    cannot be checked because of a configuration problem.
    """
    try:
        authenticator = TwoFactorAuthenticator(user.id, user.username)
        return authenticator.check_totp_code(totp_code)
    except exceptions.TOTPError as error:
        logger.error(
            "bot.handler.auth_processing.twofa_processing.totp.unavailable.fail",
            error=error.sanitized_message(),
        )
        bot.reply_to(message, TOTP_UNAVAILABLE_TEXT)
        return None


def _complete_authentication(message: Message, bot: TeleBot, user_id: int) -> None:
    """Mark the session authenticated and offer the pending screen, if any."""
    bot.send_chat_action(message.chat.id, "typing")
    session_manager.set_auth_state(user_id, session_manager.state_fabric.AUTHENTICATED)
    session_manager.set_login_time(user_id)
    # Earlier mistakes must not carry over into the next 2FA prompt.
    session_manager.reset_totp_attempts(user_id)

    keyboard = __create_referer_keyboard(user_id)

    emojis = {
        "bullseye": em.get_emoji("bullseye"),
        "down-right_arrow": em.get_emoji("down-right_arrow"),
        "saluting_face": em.get_emoji("saluting_face"),
    }

    response = Compiler.quick_render(template_name="a_success.jinja2", emojis=emojis)

    bot.reply_to(message, text=response, reply_markup=keyboard)


def _handle_rate_limited_totp_attempt(message: Message, bot: TeleBot) -> None:
    """Handle short-window TOTP burst attempts."""
    if message.from_user is None:
        return

    user_id = message.from_user.id
    session_manager.set_blocked_time(user_id=user_id, duration_minutes=1)
    logger.warning(
        "bot.handler.auth_processing.twofa_processing.totp.rate.limit.warn",
        user_id=user_id,
        window_seconds=_TOTP_RATE_LIMIT_WINDOW_SECONDS,
        threshold=_totp_rate_limit_threshold(),
    )
    bot.reply_to(
        message,
        "Too many TOTP attempts. Please wait 1 minute and try again.",
    )


def _handle_blocked_user(message: Message, bot: TeleBot) -> None:
    """
    Handle a blocked user by logging an error message and sending a blocked message to the user.

    Args:
        message (Message): The message object received from the user.
        bot (TeleBot): The TeleBot instance.

    Returns:
        None
    """
    logger.error("bot.handler.auth_processing.twofa_processing.user.blocked.deny")
    bot.reply_to(message, "Too many failed attempts. Please try again later.")


def _send_totp_code_message(message: Message, bot: TeleBot) -> None:
    """
    Asks the user for a TOTP code (private chats only).

    Parameters:
        message (Message): The message object received from the user.
        bot (TeleBot): The TeleBot instance.

    Returns:
        None
    """
    emojis = {
        "thought_balloon": em.get_emoji("thought_balloon"),
        "double_exclamation_mark": em.get_emoji("double_exclamation_mark"),
        "down_arrow": em.get_emoji("down_arrow"),
    }

    first_name = message.from_user.first_name if message.from_user else None
    username = message.from_user.username if message.from_user else None
    name = first_name or username or "User"

    response = Compiler.quick_render(
        template_name="a_send_totp_code.jinja2", name=name, **emojis
    )

    send_telegram_message(
        bot=bot,
        chat_id=message.chat.id,
        text=response,
        reply_markup=keyboards.build_reply_keyboard(keyboard_type="back_keyboard"),
        parse_mode="HTML",
    )


def _handle_invalid_totp_code(message: Message, bot: TeleBot) -> None:
    """
    Handles an invalid TOTP code by logging an error message and sending a reply to the user.

    Parameters:
        message (Message): The message object received from the user.
        bot (TeleBot): The TeleBot instance.

    Returns:
        None
    """
    if message.from_user is None:
        bot.reply_to(message, "Please send a 6-digit 2FA code.")
        return
    user_id = message.from_user.id
    logger.error("bot.handler.auth_processing.twofa_processing.invalid.totp.fail")
    bot.reply_to(
        message,
        "Invalid 2FA code. Please enter a 6-digit code. "
        "For example: 123456 or /123456.",
    )
    session_manager.increment_totp_attempts(user_id=user_id)


def _handle_max_attempts_reached(message: Message, bot: TeleBot) -> None:
    """
    Handles the scenario when the user has reached the maximum number of attempts.

    Parameters:
        message (Message): The message object received from the user.
        bot (TeleBot): The TeleBot instance.

    Returns:
        None
    """
    if message.from_user is None:
        bot.reply_to(
            message,
            "You have reached the maximum number of attempts. Please try again later.",
        )
        return
    user_id = message.from_user.id
    _block_user(user_id)
    bot.reply_to(
        message,
        "You have reached the maximum number of attempts. Please try again later.",
    )


def _block_user(user_id: int) -> None:
    """
    Blocks a user by setting their authentication state to 'blocked', resetting their TOTP attempts,
    and setting a blocked time.

    Parameters:
        user_id (int): The ID of the user to block.

    Returns:
        None
    """
    session_manager.set_auth_state(user_id, session_manager.state_fabric.BLOCKED)

    session_manager.reset_totp_attempts(user_id)

    session_manager.set_blocked_time(user_id)

    logger.error("bot.handler.auth_processing.twofa_processing.processing.blocked.deny")


def __create_referer_keyboard(
    user_id: int,
) -> ReplyKeyboardMarkup | InlineKeyboardMarkup:
    """
    Creates a referer keyboard based on the user's handler type and referer URI.

    Without a pending screen (2FA started from the menu, or the pending action
    expired) the main menu is offered instead.

    Args:
        user_id (int): The ID of the user.

    Returns:
        Union[ReplyKeyboardMarkup, InlineKeyboardMarkup]: The created referer keyboard.
    """
    handler_type = session_manager.get_handler_type(user_id)
    referer_uri = session_manager.get_referer_uri(user_id) or ""

    try:
        keyboard: ReplyKeyboardMarkup | InlineKeyboardMarkup
        if not handler_type or not referer_uri:
            keyboard = keyboards.build_reply_keyboard()
        elif handler_type == "message":
            keyboard = keyboards.build_referer_main_keyboard(referer_uri)
        elif handler_type == "callback_query":
            keyboard = _build_return_inline_keyboard(referer_uri)
        else:
            raise NotImplementedError(f"Unsupported handler type: {handler_type}")

        return keyboard

    except Exception as error:
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed to create referer keyboard",
                error_code="SESMGR_001",
                metadata={"exception": str(error)},
            )
        ) from error
    finally:
        session_manager.reset_referer_data(user_id)


def _build_return_inline_keyboard(
    referer_uri: str,
) -> ReplyKeyboardMarkup | InlineKeyboardMarkup:
    """Offer the pending screen; state-changing actions map to their overview."""
    return_callback = post_auth_return_callback(referer_uri)
    if return_callback is None:
        return keyboards.build_reply_keyboard()
    return keyboards.build_referer_inline_keyboard(
        return_callback, label=post_auth_return_label(return_callback)
    )
