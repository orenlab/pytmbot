#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from typing import Union, Dict, Any

from telebot import TeleBot
from telebot.types import Message, CallbackQuery

from pytmbot import exceptions
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import keyboards, em
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()


def _get_user_name(query: Union[Message, CallbackQuery]) -> str:
    """
    Extracts user name from query.

    Args:
        query (Union[Message, CallbackQuery]): The query object.

    Returns:
        str: User's first name or username.
    """
    return query.from_user.first_name or query.from_user.username


def _send_response(
    query: Union[Message, CallbackQuery], bot: TeleBot, response: str, keyboard: Any
) -> None:
    """
    Sends response to user based on query type.

    Args:
        query (Union[Message, CallbackQuery]): The query object.
        bot (TeleBot): The bot object.
        response (str): Response text.
        keyboard: Reply keyboard markup.

    Returns:
        None
    """
    if isinstance(query, CallbackQuery):
        bot.delete_message(query.message.chat.id, query.message.message_id)
        bot.send_message(
            query.message.chat.id,
            text=response,
            reply_markup=keyboard,
            parse_mode="HTML",
        )
    else:
        bot.send_message(
            query.chat.id, text=response, reply_markup=keyboard, parse_mode="HTML"
        )


def _handle_auth_message(
    query: Union[Message, CallbackQuery],
    bot: TeleBot,
    template_name: str,
    keyboard_type: str,
    emojis: Dict[str, str],
    error_code: str,
    error_message: str,
) -> None:
    """
    Common handler for authentication-related messages.

    Args:
        query (Union[Message, CallbackQuery]): The query object.
        bot (TeleBot): The bot object.
        template_name (str): Template name for compilation.
        keyboard_type (str): Type of keyboard to build.
        emojis (Dict[str, str]): Dictionary of emojis to use.
        error_code (str): Error code for exception.
        error_message (str): Error message for exception.

    Raises:
        NotImplementedError: If query type is not supported.
        AuthError: If handling fails.

    Returns:
        None
    """
    if not isinstance(query, (Message, CallbackQuery)):
        raise NotImplementedError("Unsupported query type")

    try:
        keyboard = keyboards.build_reply_keyboard(keyboard_type=keyboard_type)
        user_name = _get_user_name(query)

        with Compiler(
            template_name=template_name, name=user_name, **emojis
        ) as compiler:
            response = compiler.compile()

        _send_response(query, bot, response, keyboard)

    except Exception as error:
        raise exceptions.AuthError(
            ErrorContext(
                message=error_message,
                error_code=error_code,
                metadata={"exception": str(error)},
            )
        )


@logger.session_decorator
def handle_unauthorized_message(
    query: Union[Message, CallbackQuery], bot: TeleBot
) -> None:
    """
    Handles unauthorized messages received by the bot.

    Args:
        query (Union[Message, CallbackQuery]): The message or callback query received by the bot.
        bot (TeleBot): The TeleBot instance.

    Raises:
        NotImplementedError: If the query type is not supported.

    Returns:
        None
    """
    emojis = {
        "thought_balloon": em.get_emoji("thought_balloon"),
        "desktop_computer": em.get_emoji("desktop_computer"),
        "fountain_pen": em.get_emoji("fountain_pen"),
        "first_quarter_moon": em.get_emoji("first_quarter_moon"),
        "double_exclamation_mark": em.get_emoji("double_exclamation_mark"),
    }

    _handle_auth_message(
        query=query,
        bot=bot,
        template_name="a_auth_required.jinja2",
        keyboard_type="auth_keyboard",
        emojis=emojis,
        error_code="AUTH_001",
        error_message="Failed handling unauthorized message",
    )


@logger.session_decorator
def handle_access_denied(query: Union[Message, CallbackQuery], bot: TeleBot):
    """
    Handles access denied queries from users.

    Args:
        query (Union[Message, CallbackQuery]): The query object.
        bot (TeleBot): The bot object.

    Raises:
        NotImplementedError: If query is not an instance of Message or CallbackQuery.

    Returns:
        None
    """
    emojis = {
        "thought_balloon": em.get_emoji("thought_balloon"),
        "crying_face": em.get_emoji("crying_face"),
        "double_exclamation_mark": em.get_emoji("double_exclamation_mark"),
    }

    _handle_auth_message(
        query=query,
        bot=bot,
        template_name="a_access_denied.jinja2",
        keyboard_type="back_keyboard",
        emojis=emojis,
        error_code="AUTH_002",
        error_message="Failed handling access denied",
    )
