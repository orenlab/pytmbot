#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from telebot import TeleBot
from telebot.types import CallbackQuery, InlineKeyboardMarkup

from pytmbot.exceptions import DockerConnectionError, DockerOperationException
from pytmbot.handlers.docker_handlers.user_messages import DOCKER_UNAVAILABLE_TEXT
from pytmbot.handlers.handlers_util.docker import (
    CommandArgumentsView,
    authorize_docker_callback_request,
    command_arguments_view,
    get_required_callback_data,
    show_handler_info,
)
from pytmbot.handlers.handlers_util.rich_messages import build_rich_html_message
from pytmbot.handlers.server_handlers.inline.common import edit_callback_message_text
from pytmbot.logs import Logger

logger = Logger()

INVALID_IMAGE_BUTTON_TEXT: Final[str] = (
    "This image button is outdated. Open the images list again."
)
IMAGE_NOT_FOUND_TEXT: Final[str] = (
    "Image not found. It may have been removed — refresh the images list."
)
IMAGE_DETAILS_FAILED_TEXT: Final[str] = "Couldn't load image details right now."

type _Rendered = tuple[str, InlineKeyboardMarkup]


def _render_or_explain[ParsedT](
    parsed: ParsedT,
    arguments_view: CommandArgumentsView,
    render_callback: Callable[[ParsedT, CommandArgumentsView], _Rendered | None],
) -> tuple[_Rendered | None, str | None]:
    """Render the view, or return the reason it cannot be shown."""
    try:
        rendered = render_callback(parsed, arguments_view)
    except DockerConnectionError:
        return None, DOCKER_UNAVAILABLE_TEXT
    except DockerOperationException:
        logger.warning("bot.handler.docker.image_callback.render.fail")
        return None, IMAGE_DETAILS_FAILED_TEXT
    if rendered is None:
        return None, IMAGE_NOT_FOUND_TEXT
    return rendered, None


def handle_image_details_callback[ParsedT](
    *,
    call: CallbackQuery,
    bot: TeleBot,
    parse_callback: Callable[[str], ParsedT | None],
    extract_user_id: Callable[[ParsedT], int],
    render_callback: Callable[[ParsedT, CommandArgumentsView], _Rendered | None],
) -> None:
    """
    Process shared image callback flow (validate, authorize, render, edit).

    ``render_callback`` gets the parsed payload and the command arguments view
    of the verified presser in this chat (``command_arguments_view``).
    """
    callback_data = get_required_callback_data(
        call=call,
        bot=bot,
        missing_message_text="This image details message can no longer be updated.",
        invalid_button_text="This image details button is no longer valid.",
        alert_handler=show_handler_info,
    )
    if callback_data is None:
        return None

    parsed = parse_callback(callback_data)
    if parsed is None:
        show_handler_info(call=call, text=INVALID_IMAGE_BUTTON_TEXT, bot=bot)
        return None

    is_allowed, deny_reason = authorize_docker_callback_request(
        call=call,
        called_user_id=extract_user_id(parsed),
        require_admin=False,
        require_owner_match=True,
        require_session=False,
    )
    if not is_allowed:
        show_handler_info(call=call, text=f"Images: {deny_reason}", bot=bot)
        return None

    rendered, rejection_text = _render_or_explain(
        parsed, command_arguments_view(call), render_callback
    )
    if rendered is None:
        show_handler_info(
            call=call, text=rejection_text or IMAGE_NOT_FOUND_TEXT, bot=bot
        )
        return None

    context, inline_keyboard = rendered
    edit_callback_message_text(
        call=call,
        bot=bot,
        rich_message=build_rich_html_message(context),
        reply_markup=inline_keyboard,
        not_modified_text="Image details are already current.",
    )
    return None
