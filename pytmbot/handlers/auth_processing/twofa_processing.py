#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from datetime import datetime

from telebot import TeleBot
from telebot.types import Message

from pytmbot import exceptions
from pytmbot.globals import config, session_manager, em, keyboards
from pytmbot.logs import bot_logger, logged_handler_session
from pytmbot.parsers.compiler import Compiler
from pytmbot.utils.totp import TwoFactorAuthenticator
from pytmbot.utils.utilities import is_valid_totp_code

allowed_admins_ids = set(config.allowed_admins_ids)


# regexp='Enter 2FA code'
@logged_handler_session
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

        session_manager.set_auth_state(user_id, session_manager.state_fabric.processing)

        _send_totp_code_message(message, bot)

    except Exception as error:
        raise exceptions.PyTMBotErrorHandlerError(f"Failed at {__name__}: {error}")


# regexp=r"[0-9]{6}$"
@logged_handler_session
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
    totp_code: str = message.text.replace('/', '')

    if not is_valid_totp_code(totp_code):
        _handle_invalid_totp_code(message, bot)
        return

    if session_manager.get_blocked_time(user_id) and datetime.now() < session_manager.get_blocked_time(user_id):
        _handle_blocked_user(message, bot)
        return

    attempts: int = session_manager.get_totp_attempts(user_id)
    if attempts > config.totp_max_attempts:
        _handle_max_attempts_reached(message, bot)
        return

    authenticator = TwoFactorAuthenticator(user_id, message.from_user.username)
    if authenticator.verify_totp_code(totp_code):
        session_manager.set_auth_state(user_id, session_manager.state_fabric.authenticated)
        session_manager.set_login_time(user_id)
        bot_logger.log("SUCCESS", f'TOTP code for user {user_id} verified.')
        bot.reply_to(message, 'TOTP code verified. Authentication successful.')
    else:
        session_manager.set_totp_attempts(user_id=user_id)
        bot_logger.error(f"Invalid TOTP code: {totp_code}")
        bot.reply_to(message, 'Invalid TOTP code. Please try again.')


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
    bot_logger.error(f"User {user_id} is blocked")
    bot.reply_to(message, 'You are blocked. Please try again later.')


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
        'thought_balloon': em.get_emoji('thought_balloon'),
    }

    name = message.from_user.first_name if message.from_user.first_name else message.from_user.username

    keyboard = keyboards.build_reply_keyboard(keyboard_type='back_keyboard')

    with Compiler(template_name=config.known_templates['a_send_totp_code.jinja2'], name=name, **emojis) as compiler:
        response = compiler.compile()

    bot.send_message(message.chat.id, text=response, reply_markup=keyboard, parse_mode="Markdown")


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
    bot_logger.error(f"Invalid TOTP code: {message.text}")
    bot.reply_to(message, 'Invalid TOTP code. Please enter a 6-digit code. For example, /123456.')
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
    bot.reply_to(message, 'You have reached the maximum number of attempts. Please try again later.')


def _block_user(user_id: int) -> None:
    """
    Blocks a user by setting their authentication state to 'blocked', resetting their TOTP attempts,
    and setting a blocked time.

    Parameters:
        user_id (int): The ID of the user to block.

    Returns:
        None
    """
    session_manager.set_auth_state(user_id, session_manager.state_fabric.blocked)

    session_manager.reset_totp_attempts(user_id)

    session_manager.set_blocked_time(user_id)

    bot_logger.error(f"Processing blocked user {user_id}.")
