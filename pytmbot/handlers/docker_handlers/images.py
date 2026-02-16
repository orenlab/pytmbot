#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from threading import RLock
from typing import Any, Final

from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, Message

from pytmbot import exceptions
from pytmbot.adapters.docker.images_info import fetch_image_details
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

IMAGES_PAGE_CALLBACK_PREFIX: Final[str] = "__images_page__"
IMAGES_DEFAULT_PAGE_SIZE: Final[int] = 2
IMAGES_CACHE_TTL_SECONDS: Final[float] = 30.0

MAX_LIST_FIELD_ITEMS: Final[int] = 6
MAX_TEXT_FIELD_LENGTH: Final[int] = 120
MAX_LIST_ITEM_LENGTH: Final[int] = 90
MAX_LABEL_ITEMS: Final[int] = 6
MAX_LABEL_KEY_LENGTH: Final[int] = 48
MAX_LABEL_VALUE_LENGTH: Final[int] = 96

_images_cache_lock = RLock()
_images_cache: tuple[list[dict[str, Any]], float] | None = None


def _get_images_emojis() -> dict[str, str]:
    return {
        "thought_balloon": em.get_emoji("thought_balloon"),
        "spouting_whale": em.get_emoji("spouting_whale"),
        "minus": em.get_emoji("minus"),
        "package": em.get_emoji("package"),
        "bookmark_tabs": em.get_emoji("bookmark_tabs"),
        "gear": em.get_emoji("gear"),
        "desktop_computer": em.get_emoji("desktop_computer"),
        "floppy_disk": em.get_emoji("floppy_disk"),
        "mantelpiece_clock": em.get_emoji("mantelpiece_clock"),
        "person_technologist": em.get_emoji("person_technologist"),
        "wrench": em.get_emoji("wrench"),
        "label": em.get_emoji("label"),
        "electric_plug": em.get_emoji("electric_plug"),
        "key": em.get_emoji("key"),
        "arrow_right": em.get_emoji("arrow_right"),
        "computer_mouse": em.get_emoji("computer_mouse"),
    }


def _truncate_text(value: Any, *, max_length: int) -> str:
    raw = str(value) if value is not None else "N/A"
    if len(raw) <= max_length:
        return raw
    return f"{raw[: max_length - 3]}..."


def _truncate_list(
    value: Any,
    *,
    max_items: int = MAX_LIST_FIELD_ITEMS,
    max_item_length: int = MAX_LIST_ITEM_LENGTH,
) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []

    normalized = [
        _truncate_text(item, max_length=max_item_length) for item in list(value)[:max_items]
    ]
    if len(value) > max_items:
        normalized.append(f"... +{len(value) - max_items} more")
    return normalized


def _truncate_labels(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}

    normalized: dict[str, str] = {}
    for index, (key, raw_value) in enumerate(value.items()):
        if index >= MAX_LABEL_ITEMS:
            normalized["__truncated__"] = f"+{len(value) - MAX_LABEL_ITEMS} more"
            break
        safe_key = _truncate_text(key, max_length=MAX_LABEL_KEY_LENGTH)
        safe_value = _truncate_text(raw_value, max_length=MAX_LABEL_VALUE_LENGTH)
        normalized[safe_key] = safe_value

    return normalized


def _compact_image_for_listing(image: dict[str, Any]) -> dict[str, Any]:
    """Compact large image fields so one item always fits Telegram limits."""
    return {
        "id": _truncate_text(image.get("id", "N/A"), max_length=MAX_TEXT_FIELD_LENGTH),
        "name": _truncate_text(image.get("name", "N/A"), max_length=MAX_TEXT_FIELD_LENGTH),
        "tags": _truncate_list(image.get("tags", []), max_items=MAX_LIST_FIELD_ITEMS),
        "architecture": _truncate_text(
            image.get("architecture", "N/A"), max_length=MAX_TEXT_FIELD_LENGTH
        ),
        "os": _truncate_text(image.get("os", "N/A"), max_length=MAX_TEXT_FIELD_LENGTH),
        "size": _truncate_text(image.get("size", "N/A"), max_length=MAX_TEXT_FIELD_LENGTH),
        "created": _truncate_text(
            image.get("created", "N/A"), max_length=MAX_TEXT_FIELD_LENGTH
        ),
        "author": _truncate_text(
            image.get("author", "N/A"), max_length=MAX_TEXT_FIELD_LENGTH
        ),
        "docker_version": _truncate_text(
            image.get("docker_version", "N/A"), max_length=MAX_TEXT_FIELD_LENGTH
        ),
        "labels": _truncate_labels(image.get("labels", {})),
        "exposed_ports": _truncate_list(
            image.get("exposed_ports", []),
            max_items=MAX_LIST_FIELD_ITEMS,
            max_item_length=MAX_LIST_ITEM_LENGTH,
        ),
        "env_variables": _truncate_list(
            image.get("env_variables", []),
            max_items=MAX_LIST_FIELD_ITEMS,
            max_item_length=MAX_LIST_ITEM_LENGTH,
        ),
        "entrypoint": _truncate_list(
            image.get("entrypoint", []),
            max_items=MAX_LIST_FIELD_ITEMS,
            max_item_length=MAX_LIST_ITEM_LENGTH,
        ),
        "cmd": _truncate_list(
            image.get("cmd", []),
            max_items=MAX_LIST_FIELD_ITEMS,
            max_item_length=MAX_LIST_ITEM_LENGTH,
        ),
    }


def _prepare_images_for_listing(images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_compact_image_for_listing(image) for image in images if isinstance(image, dict)]


def _load_images_data() -> list[dict[str, Any]]:
    """Load image list with short-lived cache to speed up pagination navigation."""
    global _images_cache

    now = time.time()
    with _images_cache_lock:
        if _images_cache is not None:
            cached_images, cached_at = _images_cache
            if now - cached_at < IMAGES_CACHE_TTL_SECONDS:
                return [dict(image) for image in cached_images]

    images = fetch_image_details()
    if images is None:
        raise exceptions.DockerOperationException(
            ErrorContext(
                message="Failed to fetch Docker images",
                error_code="DOCKER_003",
                metadata={"reason": "images_fetch_none"},
            )
        )

    normalized = [image for image in images if isinstance(image, dict)]
    with _images_cache_lock:
        _images_cache = (normalized, now)

    return [dict(image) for image in normalized]


def _render_images_page_text(
    page_items: list[dict[str, Any]],
    *,
    page: int,
    total_pages: int,
    total_items: int,
) -> str:
    template_context = {
        "images": page_items,
        "emojis": _get_images_emojis(),
    }
    rendered = Compiler.quick_render(
        template_name="d_images.jinja2",
        context=template_context,
    )
    footer = (
        f"\n\n<i>Page {page}/{total_pages} | "
        f"Shown: {len(page_items)} | Total images: {total_items}</i>"
    )
    return f"{rendered}{footer}"


def _render_paginated_images_text(
    images: list[dict[str, Any]],
    *,
    page: int,
    initial_page_size: int = IMAGES_DEFAULT_PAGE_SIZE,
) -> tuple[str, int, int]:
    page_size = min(max(1, initial_page_size), max(1, len(images)))

    while page_size >= 1:
        window = paginate_items(images, page, page_size)
        text = _render_images_page_text(
            window.items,
            page=window.page,
            total_pages=window.total_pages,
            total_items=window.total_items,
        )
        if len(text) <= MAX_TELEGRAM_MESSAGE_LENGTH:
            return text, window.page, window.total_pages

        if page_size == 1:
            break
        page_size -= 1

    fallback = (
        f"{em.get_emoji('warning')} <b>Images view is too large for Telegram.</b>\n"
        f"{em.get_emoji('thought_balloon')} Try opening a different page."
    )
    return fallback, 1, 1


def _build_images_keyboard(
    *,
    page: int,
    total_pages: int,
    user_id: int,
) -> InlineKeyboardMarkup:
    keyboard_buttons = []

    if total_pages > 1 and page > 1:
        keyboard_buttons.append(
            button_data(
                text=f"{em.get_emoji('BACK_arrow')} Prev",
                callback_data=build_page_callback_data(
                    prefix=IMAGES_PAGE_CALLBACK_PREFIX,
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
                    prefix=IMAGES_PAGE_CALLBACK_PREFIX,
                    page=page + 1,
                    user_id=user_id,
                ),
            )
        )

    keyboard_buttons.append(
        button_data(
            text="Check updates",
            callback_data=f"__check_updates__:{user_id}",
        )
    )

    return keyboards.build_inline_keyboard(keyboard_buttons)


def render_images_page(
    *,
    page: int,
    user_id: int,
) -> tuple[str, InlineKeyboardMarkup]:
    """Build paginated images text and keyboard for requested page."""
    images = _load_images_data()

    prepared_images = _prepare_images_for_listing(images)
    text, safe_page, total_pages = _render_paginated_images_text(
        prepared_images,
        page=page,
    )
    keyboard = _build_images_keyboard(
        page=safe_page,
        total_pages=total_pages,
        user_id=user_id,
    )
    return text, keyboard


@logger.session_decorator
def handle_images(message: Message, bot: TeleBot) -> bool:
    """
    Handler for the 'images' command with paginated output.
    """
    try:
        bot.send_chat_action(message.chat.id, "typing")

        user_id = int(message.from_user.id) if message.from_user else 0
        bot_answer, inline_button = render_images_page(page=1, user_id=user_id)

        return send_telegram_message(
            bot,
            message.chat.id,
            bot_answer,
            inline_button,
            "HTML",
        )

    except Exception as error:
        bot.send_message(
            message.chat.id, "⚠️ An error occurred while processing the command."
        )
        logger.error(
            "bot.handler.docker.images.fail",
            extra={
                "chat_id": message.chat.id,
                "error": str(error),
                "error_type": type(error).__name__,
            },
        )
        raise exceptions.HandlingException(
            ErrorContext(
                message="Images handler error",
                error_code="HAND_010",
                metadata={"exception": str(error)},
            )
        ) from error
