#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from datetime import datetime
from typing import Union

from telebot import TeleBot
from telebot.types import Message, ReplyKeyboardMarkup, InlineKeyboardMarkup

from pytmbot import exceptions
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import session_manager, em, keyboards, settings, var_config
from pytmbot.handlers.handlers_util.utils import send_telegram_message
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler
from pytmbot.utils import is_valid_totp_code
from pytmbot.utils.totp import TwoFactorAuthenticator

logger = Logger()
allowed_admins_ids = set(settings.access_control.allowed_admins_ids)


# regexp='Enter 2FA code'
@logger.session_decorator
def handle_twofa_message(message: Message, bot: TeleBot):
    """
    Handle the 'Enter 2FA code' message.

    Args:
        message (Message): The message object received from the user.
        bot (TeleBot): The TeleBot instance.

    Returns:
        None
    """
    user_id = message.from_user.id
    try:
        if session_manager.is_blocked(user_id):
            _handle_blocked_user(message, bot)
            return

        session_manager.set_auth_state(user_id, session_manager.state_fabric.PROCESSING)

        _send_totp_code_message(message, bot)

    except Exception as error:
        bot.send_message(
            message.chat.id, "⚠️ An error occurred while processing the plugins command."
        )
        raise exceptions.HandlingException(ErrorContext(
            message="Failed handling the twofa command",
            error_code="HAND_020",
            metadata={"exception": str(error)}
        ))


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
    user_id: int = message.from_user.id
    totp_code: str = message.text.replace("/", "")

    if not is_valid_totp_code(totp_code):
        _handle_invalid_totp_code(message, bot)
        return

    if session_manager.get_blocked_time(
            user_id
    ) and datetime.now() < session_manager.get_blocked_time(user_id):
        _handle_blocked_user(message, bot)
        return

    attempts = session_manager.get_totp_attempts(user_id)
    if attempts > var_config.totp_max_attempts:
        _handle_max_attempts_reached(message, bot)
        return

    authenticator = TwoFactorAuthenticator(user_id, message.from_user.username)
    if authenticator.verify_totp_code(totp_code):
        bot.send_chat_action(message.chat.id, "typing")
        session_manager.set_auth_state(
            user_id, session_manager.state_fabric.AUTHENTICATED
        )
        session_manager.set_login_time(user_id)

        keyboard = __create_referer_keyboard(user_id)

        emojis = {
            "bullseye": em.get_emoji("bullseye"),
            "down-right_arrow": em.get_emoji("down-right_arrow"),
            "saluting_face": em.get_emoji("saluting_face"),
        }

        with Compiler(template_name="a_success.jinja2", emojis=emojis) as compiler:
            response = compiler.compile()

        bot.reply_to(message, text=response, reply_markup=keyboard)
    else:
        session_manager.increment_totp_attempts(user_id=user_id)
        logger.error(f"Invalid TOTP code: {totp_code}")
        bot.reply_to(message, "Invalid TOTP code. Please try again.")


def _handle_blocked_user(message: Message, bot: TeleBot) -> None:
    """
    Handle a blocked user by logging an error message and sending a blocked message to the user.

    Args:
        message (Message): The message object received from the user.
        bot (TeleBot): The TeleBot instance.

    Returns:
        None
    """
    user_id = message.from_user.id
    logger.error(f"User {user_id} is blocked")
    bot.reply_to(message, "You are blocked. Please try again later.")


def _send_totp_code_message(message: Message, bot: TeleBot) -> None:
    """
    Sends a message to the user with a TOTP code.

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

    name = (
        message.from_user.first_name
        if message.from_user.first_name
        else message.from_user.username
    )

    keyboard = keyboards.build_reply_keyboard(keyboard_type="back_keyboard")

    with Compiler(
            template_name="a_send_totp_code.jinja2", name=name, **emojis
    ) as compiler:
        response = compiler.compile()

    send_telegram_message(
        bot=bot,
        chat_id=message.chat.id,
        text=response,
        reply_markup=keyboard,
        parse_mode="HTML"
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
    user_id = message.from_user.id
    logger.error(f"Invalid TOTP code: {message.text}")
    bot.reply_to(
        message, "Invalid TOTP code. Please enter a 6-digit code. For example, /123456."
    )
    session_manager.set_totp_attempts(user_id=user_id)


def _handle_max_attempts_reached(message: Message, bot: TeleBot) -> None:
    """
    Handles the scenario when the user has reached the maximum number of attempts.

    Parameters:
        message (Message): The message object received from the user.
        bot (TeleBot): The TeleBot instance.

    Returns:
        None
    """
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

    logger.error(f"Processing blocked user {user_id}.")


def __create_referer_keyboard(
        user_id: int,
) -> Union[ReplyKeyboardMarkup, InlineKeyboardMarkup]:
    """
    Creates a referer keyboard based on the user's handler type and referer URI.

    Args:
        user_id (int): The ID of the user.

    Returns:
        Union[ReplyKeyboardMarkup, InlineKeyboardMarkup]: The created referer keyboard.
    """
    handler_type = session_manager.get_handler_type(user_id)
    referer_uri = session_manager.get_referer_uri(user_id)

    try:
        if handler_type == "message":
            keyboard = keyboards.build_referer_main_keyboard(referer_uri)
        elif handler_type == "callback_query":
            keyboard = keyboards.build_referer_inline_keyboard(referer_uri)
        else:
            raise NotImplementedError(f"Unsupported handler type: {handler_type}")

        return keyboard

    except Exception as error:
        raise exceptions.HandlingException(ErrorContext(
            message="Failed to create referer keyboard",
            error_code="SESMGR_001",
            metadata={"exception": str(error)}
        ))
    finally:
        session_manager.reset_referer_data(user_id)
