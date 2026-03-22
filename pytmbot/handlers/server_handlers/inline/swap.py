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
from pytmbot.globals import (
    ButtonDataType,
    get_emoji_converter,
    get_keyboards,
    get_psutil_adapter,
)
from pytmbot.handlers.server_handlers.inline.common import (
    authorize_user_bound_callback,
    build_user_bound_callback_data,
    edit_callback_message_text,
)
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()
em = get_emoji_converter()
button_data = ButtonDataType
keyboards = get_keyboards()
psutil_adapter = get_psutil_adapter()

SWAP_INFO_CALLBACK_PREFIX = "__swap_info__"


def _build_swap_keyboard(target_user_id: int | None) -> InlineKeyboardMarkup:
    return keyboards.build_inline_keyboard(
        button_data(
            text="Swap info",
            callback_data=build_user_bound_callback_data(
                SWAP_INFO_CALLBACK_PREFIX, target_user_id
            ),
        )
    )


# func=lambda call: call.data == '__swap_info__'
@logger.session_decorator
def handle_swap_info(call: CallbackQuery, bot: TeleBot) -> None:
    """Handles the swap_info command."""

    is_allowed, target_user_id = authorize_user_bound_callback(
        call,
        bot,
        prefix=SWAP_INFO_CALLBACK_PREFIX,
        invalid_payload_text="This button is no longer valid. Please open Memory again.",
        missing_message_text=(
            "This message can no longer be updated. Please open Memory again."
        ),
    )
    if not is_allowed:
        return None

    if call.message is None:
        return None

    emojis = {
        "thought_balloon": em.get_emoji("thought_balloon"),
        "paperclip": em.get_emoji("paperclip"),
    }
    fallback_text = (
        "Sorry, I couldn't retrieve swap information right now. Please try again later."
    )

    try:
        swap_data = psutil_adapter.get_swap_memory()

        if swap_data is None:
            edit_callback_message_text(
                call,
                bot,
                text=fallback_text,
                reply_markup=_build_swap_keyboard(target_user_id),
            )
            return None

        bot_answer = Compiler.quick_render(
            template_name="b_swap.jinja2", context=swap_data, **emojis
        )

        edit_callback_message_text(
            call,
            bot,
            text=bot_answer,
            reply_markup=_build_swap_keyboard(target_user_id),
        )
        return None
    except Exception as error:
        edit_callback_message_text(
            call,
            bot,
            text=fallback_text,
            reply_markup=_build_swap_keyboard(target_user_id),
        )
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling inline swap info",
                error_code="HAND_009",
                metadata={"exception": str(error)},
            )
        ) from error
