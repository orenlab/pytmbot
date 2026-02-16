#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from typing import Final

from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, Message

from pytmbot import exceptions
from pytmbot.adapters.docker.containers_info import retrieve_containers_stats
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import button_data, em, keyboards
from pytmbot.handlers.docker_handlers.pagination import (
    MAX_TELEGRAM_MESSAGE_LENGTH,
    build_page_callback_data,
    paginate_items,
)
from pytmbot.handlers.handlers_util.utils import send_telegram_message
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()

CONTAINERS_PAGE_CALLBACK_PREFIX: Final[str] = "__containers_page__"
CONTAINERS_DEFAULT_PAGE_SIZE: Final[int] = 8


def _get_containers_emojis() -> dict[str, str]:
    return {
        "thought_balloon": em.get_emoji("thought_balloon"),
        "oil_drum": em.get_emoji("oil_drum"),
        "id": em.get_emoji("ID_button"),
        "package": em.get_emoji("package"),
        "mantelpiece_clock": em.get_emoji("mantelpiece_clock"),
        "rocket": em.get_emoji("rocket"),
        "antenna_bars": em.get_emoji("antenna_bars"),
        "magnifying_glass": em.get_emoji("magnifying_glass_tilted_left"),
    }


def _get_container_data() -> list[dict[str, str]]:
    """Retrieve normalized container data for UI rendering."""
    try:
        data = retrieve_containers_stats()
    except Exception as e:
        raise exceptions.DockerOperationException(
            ErrorContext(
                message="Failed to retrieve container data",
                error_code="DOCKER_001",
                metadata={"exception": str(e)},
            )
        ) from e

    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def _render_empty_message() -> str:
    return Compiler.quick_render(
        template_name="b_none.jinja2",
        context="There are no containers or incorrect settings are specified.",
        thought_balloon=em.get_emoji("thought_balloon"),
    )


def _render_container_page_text(
    page_items: list[dict[str, str]],
    *,
    page: int,
    total_pages: int,
    total_items: int,
) -> str:
    text = Compiler.quick_render(
        template_name="d_containers.jinja2",
        context=page_items,
        **_get_containers_emojis(),
    )
    footer = (
        f"\n\n<i>Page {page}/{total_pages} | "
        f"Shown: {len(page_items)} | Total containers: {total_items}</i>"
    )
    return f"{text}{footer}"


def _render_paginated_container_text(
    container_data: list[dict[str, str]],
    *,
    page: int,
    initial_page_size: int = CONTAINERS_DEFAULT_PAGE_SIZE,
) -> tuple[str, list[dict[str, str]], int, int]:
    page_size = min(max(1, initial_page_size), max(1, len(container_data)))
    fallback_window = paginate_items(container_data, page, page_size)

    while page_size >= 1:
        window = paginate_items(container_data, page, page_size)
        text = _render_container_page_text(
            window.items,
            page=window.page,
            total_pages=window.total_pages,
            total_items=window.total_items,
        )
        if len(text) <= MAX_TELEGRAM_MESSAGE_LENGTH:
            return text, window.items, window.page, window.total_pages

        fallback_window = window
        if page_size == 1:
            break
        page_size -= 1

    fallback_text = (
        f"{em.get_emoji('warning')} <b>Containers view is too large for Telegram.</b>\n"
        f"<i>Page {fallback_window.page}/{fallback_window.total_pages}</i>"
    )
    return (
        fallback_text,
        fallback_window.items,
        fallback_window.page,
        fallback_window.total_pages,
    )


def _build_containers_keyboard(
    page_items: list[dict[str, str]],
    *,
    page: int,
    total_pages: int,
    user_id: int,
) -> InlineKeyboardMarkup | None:
    keyboard_buttons = []

    for container in page_items:
        container_name = str(container.get("name", "")).strip()
        container_id = str(container.get("id", "")).strip().lower()
        container_ref = container_id or container_name.lower()
        if not container_ref:
            continue

        keyboard_buttons.append(
            button_data(
                text=container_name or container_ref,
                callback_data=f"__get_full__:{container_ref}:{user_id}",
            )
        )

    if total_pages > 1 and page > 1:
        keyboard_buttons.append(
            button_data(
                text=f"{em.get_emoji('BACK_arrow')} Prev",
                callback_data=build_page_callback_data(
                    prefix=CONTAINERS_PAGE_CALLBACK_PREFIX,
                    page=page - 1,
                    user_id=user_id,
                ),
            )
        )

    if total_pages > 1 and page < total_pages:
        keyboard_buttons.append(
            button_data(
                text=f"Next {em.get_emoji('next_track_button')}",
                callback_data=build_page_callback_data(
                    prefix=CONTAINERS_PAGE_CALLBACK_PREFIX,
                    page=page + 1,
                    user_id=user_id,
                ),
            )
        )

    if not keyboard_buttons:
        return None

    return keyboards.build_inline_keyboard(keyboard_buttons)


def render_containers_page(
    *,
    page: int,
    user_id: int,
) -> tuple[str, InlineKeyboardMarkup | None]:
    """Build paginated containers text and keyboard for requested page."""
    container_data = _get_container_data()
    if not container_data or container_data == [{}]:
        return _render_empty_message(), None

    text, page_items, safe_page, total_pages = _render_paginated_container_text(
        container_data,
        page=page,
    )
    keyboard = _build_containers_keyboard(
        page_items,
        page=safe_page,
        total_pages=total_pages,
        user_id=user_id,
    )
    return text, keyboard


# regexp="Containers"
# commands=["containers"]
@logger.session_decorator
def handle_containers(message: Message, bot: TeleBot) -> None:
    """
    Handle the 'Containers' message by rendering and sending paginated container list.
    """
    try:
        bot.send_chat_action(message.chat.id, "typing")
        user_id = int(message.from_user.id) if message.from_user else 0

        context, inline_keyboard = render_containers_page(page=1, user_id=user_id)

        send_telegram_message(
            bot=bot,
            chat_id=message.chat.id,
            text=context,
            reply_markup=inline_keyboard,
            parse_mode="HTML",
        )

    except Exception as error:
        bot.send_message(
            message.chat.id, "⚠️ An error occurred while processing the command."
        )
        raise exceptions.HandlingException(
            ErrorContext(
                message="Failed handling containers",
                error_code="HAND_012",
                metadata={"exception": str(error)},
            )
        ) from error


def get_list_of_containers_again(
    *,
    page: int = 1,
    user_id: int,
) -> tuple[str, InlineKeyboardMarkup | None]:
    """
    Return paginated container list for callbacks that re-open containers screen.
    """
    return render_containers_page(page=page, user_id=user_id)
