#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from pytmbot import exceptions
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import ButtonDataType, get_emoji_converter, get_keyboards
from pytmbot.handlers.handlers_util.callback_auth import (
    authorize_callback_request,
    parse_callback_target_user,
)
from pytmbot.handlers.server_handlers.inline.common import (
    build_user_bound_callback_data,
    edit_callback_message_text,
)
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()
em = get_emoji_converter()
button_data = ButtonDataType
keyboards = get_keyboards()

UPDATE_INFO_CALLBACK_PREFIX = "__how_update__"


def _build_update_info_keyboard(target_user_id: int | None) -> InlineKeyboardMarkup:
    return keyboards.build_inline_keyboard(
        button_data(
            text="Update guide",
            callback_data=build_user_bound_callback_data(
                UPDATE_INFO_CALLBACK_PREFIX, target_user_id
            ),
        )
    )


# func=lambda call: call.data == '__how_update__'
@logger.session_decorator
def handle_update_info(call: CallbackQuery, bot: TeleBot) -> object | None:
    """
    Handle the 'check_update_info' command

    Args:
        call (CallbackQuery): The callback query received by the bot.
        bot (TeleBot): The bot instance.

    Returns:
        None
    """
    try:
        target_user_id = parse_callback_target_user(
            call.data or "", UPDATE_INFO_CALLBACK_PREFIX
        )
    except ValueError:
        return bot.answer_callback_query(
            callback_query_id=call.id,
            text="This update button is no longer valid. Run /check_bot_updates again.",
            show_alert=True,
        )

    is_allowed, deny_reason = authorize_callback_request(
        call,
        target_user_id=target_user_id,
        require_owner_match=target_user_id is not None,
    )
    if not is_allowed:
        return bot.answer_callback_query(
            callback_query_id=call.id,
            text=deny_reason,
            show_alert=True,
        )

    if call.message is None:
        return bot.answer_callback_query(
            callback_query_id=call.id,
            text=(
                "This update message can no longer be refreshed. "
                "Run /check_bot_updates again."
            ),
            show_alert=True,
        )

    emojis = {"thought_balloon": em.get_emoji("thought_balloon")}

    try:
        bot_answer = Compiler.quick_render(
            template_name="b_how_update.jinja2", **emojis
        )

        edit_callback_message_text(
            call=call,
            bot=bot,
            text=bot_answer,
            parse_mode="HTML",
            reply_markup=_build_update_info_keyboard(target_user_id),
            not_modified_text="Update guide is already current.",
        )
        return None
    except Exception as error:
        if call.message is not None:
            edit_callback_message_text(
                call=call,
                bot=bot,
                text=(
                    "Couldn't load the update guide right now. Please try again later."
                ),
                reply_markup=_build_update_info_keyboard(target_user_id),
                not_modified_text="Update guide is already current.",
            )
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling update info",
                error_code="HAND_019",
                metadata={"exception": str(error)},
            )
        ) from error
