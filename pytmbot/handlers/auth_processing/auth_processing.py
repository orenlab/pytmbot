#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from typing import Union

from telebot import TeleBot
from telebot.types import Message, CallbackQuery

from pytmbot import exceptions
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import keyboards, em
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()


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
    if not isinstance(query, (Message, CallbackQuery)):
        raise NotImplementedError("Unsupported query type")

    try:
        keyboard = keyboards.build_reply_keyboard(keyboard_type="auth_keyboard")

        emojis = {
            "thought_balloon": em.get_emoji("thought_balloon"),
            "desktop_computer": em.get_emoji("desktop_computer"),
            "fountain_pen": em.get_emoji("fountain_pen"),
            "first_quarter_moon": em.get_emoji("first_quarter_moon"),
            "double_exclamation_mark": em.get_emoji("double_exclamation_mark"),
        }

        name = (
            query.from_user.first_name
            if query.from_user.first_name
            else query.from_user.username
        )

        with Compiler(
            template_name="a_auth_required.jinja2", name=name, **emojis
        ) as compiler:
            response = compiler.compile()

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
    except Exception as error:
        raise exceptions.AuthError(
            ErrorContext(
                message="Failed handling unauthorized message",
                error_code="AUTH_001",
                metadata={"exception": str(error)},
            )
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
    if not isinstance(query, (Message, CallbackQuery)):
        raise NotImplementedError("Unsupported query type")

    try:
        user_name = query.from_user.first_name or query.from_user.username
        keyboard = keyboards.build_reply_keyboard(keyboard_type="back_keyboard")
        emojis = {
            "thought_balloon": em.get_emoji("thought_balloon"),
            "crying_face": em.get_emoji("crying_face"),
            "double_exclamation_mark": em.get_emoji("double_exclamation_mark"),
        }

        with Compiler(
            template_name="a_access_denied.jinja2", name=user_name, **emojis
        ) as compiler:
            response = compiler.compile()

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
    except Exception as error:
        raise exceptions.AuthError(
            ErrorContext(
                message="Failed handling access denied",
                error_code="AUTH_002",
                metadata={"exception": str(error)},
            )
        )
