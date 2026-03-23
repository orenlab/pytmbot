#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from telebot import TeleBot
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from pytmbot.handlers.docker_handlers.images import (
    parse_image_info_callback_data,
    render_image_details,
)
from pytmbot.handlers.docker_handlers.inline.image_callback import (
    handle_image_details_callback,
)
from pytmbot.logs import Logger

logger = Logger()


def _extract_target_user_id(parsed: tuple[int, int, int]) -> int:
    return parsed[1]


def _render_from_parsed(
    parsed: tuple[int, int, int],
) -> tuple[str, InlineKeyboardMarkup] | None:
    image_index, target_user_id, page = parsed
    return render_image_details(
        image_index=image_index,
        page=page,
        user_id=target_user_id,
    )


@logger.catch()
@logger.session_decorator
def handle_image_info(call: CallbackQuery, bot: TeleBot) -> None:
    return handle_image_details_callback(
        call=call,
        bot=bot,
        parse_callback=parse_image_info_callback_data,
        extract_user_id=_extract_target_user_id,
        render_callback=_render_from_parsed,
    )
