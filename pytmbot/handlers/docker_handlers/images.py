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
from pytmbot.adapters.docker.images_info import (
    fetch_image_details,
    get_image_history,
    get_image_usage,
)
from pytmbot.exceptions import ErrorContext
from pytmbot.globals import ButtonDataType, get_emoji_converter, get_keyboards
from pytmbot.handlers.docker_handlers.pagination import (
    MAX_TELEGRAM_MESSAGE_LENGTH,
    build_page_callback_data,
    paginate_items,
)
from pytmbot.handlers.handlers_util.utils import send_telegram_message
from pytmbot.logs import Logger
from pytmbot.parsers.compiler import Compiler

logger = Logger()
button_data = ButtonDataType
em = get_emoji_converter()
keyboards = get_keyboards()

IMAGES_PAGE_CALLBACK_PREFIX: Final[str] = "__images_page__"
IMAGE_INFO_CALLBACK_PREFIX: Final[str] = "__image_info__"
IMAGE_EXTRA_CALLBACK_PREFIX: Final[str] = "__image_extra__"
IMAGES_DEFAULT_PAGE_SIZE: Final[int] = 2
IMAGES_CACHE_TTL_SECONDS: Final[float] = 30.0

MAX_LIST_FIELD_ITEMS: Final[int] = 6
MAX_TEXT_FIELD_LENGTH: Final[int] = 120
MAX_LIST_ITEM_LENGTH: Final[int] = 90
MAX_LABEL_ITEMS: Final[int] = 6
MAX_LABEL_KEY_LENGTH: Final[int] = 48
MAX_LABEL_VALUE_LENGTH: Final[int] = 96
DETAIL_MAX_LIST_FIELD_ITEMS: Final[int] = 12
DETAIL_MAX_TEXT_FIELD_LENGTH: Final[int] = 220
DETAIL_MAX_LIST_ITEM_LENGTH: Final[int] = 160
DETAIL_MAX_LABEL_ITEMS: Final[int] = 12
DETAIL_MAX_LABEL_KEY_LENGTH: Final[int] = 64
DETAIL_MAX_LABEL_VALUE_LENGTH: Final[int] = 180
DETAIL_MAX_HISTORY_ITEMS: Final[int] = 12
DETAIL_MAX_USAGE_ITEMS: Final[int] = 12

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
        "magnifying_glass": em.get_emoji("magnifying_glass_tilted_left"),
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
        _truncate_text(item, max_length=max_item_length)
        for item in list(value)[:max_items]
    ]
    if len(value) > max_items:
        normalized.append(f"... +{len(value) - max_items} more")
    return normalized


def _truncate_labels(
    value: Any,
    *,
    max_items: int = MAX_LABEL_ITEMS,
    max_key_length: int = MAX_LABEL_KEY_LENGTH,
    max_value_length: int = MAX_LABEL_VALUE_LENGTH,
) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}

    normalized: dict[str, str] = {}
    for index, (key, raw_value) in enumerate(value.items()):
        if index >= max_items:
            normalized["__truncated__"] = f"+{len(value) - max_items} more"
            break
        safe_key = _truncate_text(key, max_length=max_key_length)
        safe_value = _truncate_text(raw_value, max_length=max_value_length)
        normalized[safe_key] = safe_value

    return normalized


def _safe_positive_int(value: Any, *, default: int = 0) -> int:
    if isinstance(value, int) and value >= 0:
        return value
    return default


def _compact_image(
    image: dict[str, Any],
    *,
    max_text_length: int,
    max_list_items: int,
    max_list_item_length: int,
    max_label_items: int,
    max_label_key_length: int,
    max_label_value_length: int,
) -> dict[str, Any]:
    tags_raw = image.get("tags", [])
    tags_total = len(tags_raw) if isinstance(tags_raw, Sequence) else 0
    tags = _truncate_list(
        tags_raw,
        max_items=max_list_items,
        max_item_length=max_list_item_length,
    )
    repo_digests_raw = image.get("repo_digests", [])
    repo_digests_total = (
        len(repo_digests_raw) if isinstance(repo_digests_raw, Sequence) else 0
    )
    repo_digests = _truncate_list(
        repo_digests_raw,
        max_items=max_list_items,
        max_item_length=max_list_item_length,
    )
    exposed_ports_raw = image.get("exposed_ports", [])
    exposed_ports_total = (
        len(exposed_ports_raw) if isinstance(exposed_ports_raw, Sequence) else 0
    )
    exposed_ports = _truncate_list(
        exposed_ports_raw,
        max_items=max_list_items,
        max_item_length=max_list_item_length,
    )
    env_variables_raw = image.get("env_variables", [])
    env_variables_total = (
        len(env_variables_raw) if isinstance(env_variables_raw, Sequence) else 0
    )
    env_variables = _truncate_list(
        env_variables_raw,
        max_items=max_list_items,
        max_item_length=max_list_item_length,
    )
    entrypoint = _truncate_list(
        image.get("entrypoint", []),
        max_items=max_list_items,
        max_item_length=max_list_item_length,
    )
    cmd = _truncate_list(
        image.get("cmd", []),
        max_items=max_list_items,
        max_item_length=max_list_item_length,
    )
    shell = _truncate_list(
        image.get("shell", []),
        max_items=max_list_items,
        max_item_length=max_list_item_length,
    )
    volumes_raw = image.get("volumes", [])
    volumes_total = len(volumes_raw) if isinstance(volumes_raw, Sequence) else 0
    volumes = _truncate_list(
        volumes_raw,
        max_items=max_list_items,
        max_item_length=max_list_item_length,
    )
    labels = _truncate_labels(
        image.get("labels", {}),
        max_items=max_label_items,
        max_key_length=max_label_key_length,
        max_value_length=max_label_value_length,
    )

    return {
        "id": _truncate_text(image.get("id", "N/A"), max_length=max_text_length),
        "name": _truncate_text(image.get("name", "N/A"), max_length=max_text_length),
        "tags": tags,
        "tags_count": tags_total,
        "repo_digests": repo_digests,
        "repo_digests_count": repo_digests_total,
        "architecture": _truncate_text(
            image.get("architecture", "N/A"), max_length=max_text_length
        ),
        "variant": _truncate_text(
            image.get("variant", "N/A"), max_length=max_text_length
        ),
        "os": _truncate_text(image.get("os", "N/A"), max_length=max_text_length),
        "size": _truncate_text(image.get("size", "N/A"), max_length=max_text_length),
        "virtual_size": _truncate_text(
            image.get("virtual_size", "N/A"), max_length=max_text_length
        ),
        "shared_size": _truncate_text(
            image.get("shared_size", "N/A"), max_length=max_text_length
        ),
        "created": _truncate_text(
            image.get("created", "N/A"), max_length=max_text_length
        ),
        "created_at": _truncate_text(
            image.get("created_at", "N/A"), max_length=max_text_length
        ),
        "author": _truncate_text(
            image.get("author", "N/A"), max_length=max_text_length
        ),
        "docker_version": _truncate_text(
            image.get("docker_version", "N/A"), max_length=max_text_length
        ),
        "comment": _truncate_text(
            image.get("comment", "N/A"), max_length=max_text_length
        ),
        "parent_id": _truncate_text(
            image.get("parent_id", "N/A"), max_length=max_text_length
        ),
        "rootfs_type": _truncate_text(
            image.get("rootfs_type", "N/A"), max_length=max_text_length
        ),
        "layers_count": _safe_positive_int(image.get("layers_count")),
        "labels": labels,
        "label_count": _safe_positive_int(
            image.get("label_count"),
            default=len(labels) if labels else 0,
        ),
        "exposed_ports": exposed_ports,
        "exposed_ports_count": exposed_ports_total,
        "env_variables": env_variables,
        "env_variables_count": env_variables_total,
        "entrypoint": entrypoint,
        "cmd": cmd,
        "shell": shell,
        "volumes": volumes,
        "volumes_count": volumes_total,
        "user": _truncate_text(image.get("user", "root"), max_length=max_text_length),
        "working_dir": _truncate_text(
            image.get("working_dir", "/"), max_length=max_text_length
        ),
        "stop_signal": _truncate_text(
            image.get("stop_signal", "SIGTERM"), max_length=max_text_length
        ),
        "healthcheck": _truncate_text(
            image.get("healthcheck", "none"), max_length=max_text_length
        ),
    }


def _compact_image_for_listing(image: dict[str, Any]) -> dict[str, Any]:
    """Compact large image fields so list output always fits Telegram limits."""
    return _compact_image(
        image,
        max_text_length=MAX_TEXT_FIELD_LENGTH,
        max_list_items=MAX_LIST_FIELD_ITEMS,
        max_list_item_length=MAX_LIST_ITEM_LENGTH,
        max_label_items=MAX_LABEL_ITEMS,
        max_label_key_length=MAX_LABEL_KEY_LENGTH,
        max_label_value_length=MAX_LABEL_VALUE_LENGTH,
    )


def _compact_image_for_details(image: dict[str, Any]) -> dict[str, Any]:
    """Compact image fields for detailed image view."""
    return _compact_image(
        image,
        max_text_length=DETAIL_MAX_TEXT_FIELD_LENGTH,
        max_list_items=DETAIL_MAX_LIST_FIELD_ITEMS,
        max_list_item_length=DETAIL_MAX_LIST_ITEM_LENGTH,
        max_label_items=DETAIL_MAX_LABEL_ITEMS,
        max_label_key_length=DETAIL_MAX_LABEL_KEY_LENGTH,
        max_label_value_length=DETAIL_MAX_LABEL_VALUE_LENGTH,
    )


def _prepare_images_for_listing(images: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        _compact_image_for_listing(image) for image in images if isinstance(image, dict)
    ]


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
) -> tuple[str, int, int, list[dict[str, Any]], int]:
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
            start_index = (window.page - 1) * window.page_size
            return text, window.page, window.total_pages, window.items, start_index

        if page_size == 1:
            break
        page_size -= 1

    fallback = (
        f"{em.get_emoji('warning')} <b>Images view is too large for Telegram.</b>\n"
        f"{em.get_emoji('thought_balloon')} Try opening a different page."
    )
    return fallback, 1, 1, [], 0


def build_image_info_callback_data(*, image_index: int, user_id: int, page: int) -> str:
    """Build callback payload for image details action."""
    safe_index = max(0, int(image_index))
    safe_page = max(1, int(page))
    return f"{IMAGE_INFO_CALLBACK_PREFIX}:{safe_index}:{int(user_id)}:{safe_page}"


def parse_image_info_callback_data(
    callback_data: str,
) -> tuple[int, int, int] | None:
    """Parse callback payload for image details action."""
    parts = callback_data.split(":")
    if len(parts) != 4 or parts[0] != IMAGE_INFO_CALLBACK_PREFIX:
        return None

    try:
        image_index = int(parts[1])
        user_id = int(parts[2])
        page = int(parts[3])
    except (TypeError, ValueError):
        return None

    if image_index < 0 or page < 1:
        return None

    return image_index, user_id, page


def build_image_extra_callback_data(
    *,
    action: str,
    image_index: int,
    user_id: int,
    page: int,
) -> str:
    safe_action = action.strip().lower()
    safe_index = max(0, int(image_index))
    safe_page = max(1, int(page))
    return (
        f"{IMAGE_EXTRA_CALLBACK_PREFIX}:{safe_action}:{safe_index}:"
        f"{int(user_id)}:{safe_page}"
    )


def parse_image_extra_callback_data(
    callback_data: str,
) -> tuple[str, int, int, int] | None:
    parts = callback_data.split(":")
    if len(parts) != 5 or parts[0] != IMAGE_EXTRA_CALLBACK_PREFIX:
        return None

    action = parts[1].strip().lower()
    if action not in {"history", "usage"}:
        return None

    try:
        image_index = int(parts[2])
        user_id = int(parts[3])
        page = int(parts[4])
    except (TypeError, ValueError):
        return None

    if image_index < 0 or page < 1:
        return None

    return action, image_index, user_id, page


def _make_image_details_button_label(
    image: dict[str, Any],
    *,
    image_position: int,
) -> str:
    image_name = _truncate_text(image.get("name", "N/A"), max_length=20)
    return f"{em.get_emoji('package')} #{image_position} {image_name}"


def _build_images_keyboard(
    *,
    page: int,
    total_pages: int,
    user_id: int,
    page_items: list[dict[str, Any]],
    start_index: int,
) -> InlineKeyboardMarkup:
    keyboard_buttons = []

    for item_offset, image in enumerate(page_items):
        image_index = start_index + item_offset
        keyboard_buttons.append(
            button_data(
                text=_make_image_details_button_label(
                    image,
                    image_position=image_index + 1,
                ),
                callback_data=build_image_info_callback_data(
                    image_index=image_index,
                    user_id=user_id,
                    page=page,
                ),
            )
        )

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


def _get_image_details_data(*, image_index: int) -> dict[str, Any] | None:
    images = _load_images_data()
    if image_index < 0 or image_index >= len(images):
        return None

    image = images[image_index]
    if not isinstance(image, dict):
        return None
    return _compact_image_for_details(image)


def _get_image_raw_data(*, image_index: int) -> dict[str, Any] | None:
    images = _load_images_data()
    if image_index < 0 or image_index >= len(images):
        return None

    image = images[image_index]
    return image if isinstance(image, dict) else None


def _render_image_details_text(image: dict[str, Any]) -> str:
    return Compiler.quick_render(
        template_name="d_image_full_info.jinja2",
        context={
            "image": image,
            "emojis": _get_images_emojis(),
        },
    )


def _build_image_details_keyboard(
    *,
    image_index: int,
    page: int,
    user_id: int,
) -> InlineKeyboardMarkup:
    return keyboards.build_inline_keyboard(
        [
            button_data(
                text="History",
                callback_data=build_image_extra_callback_data(
                    action="history",
                    image_index=image_index,
                    user_id=user_id,
                    page=page,
                ),
            ),
            button_data(
                text="Used by containers",
                callback_data=build_image_extra_callback_data(
                    action="usage",
                    image_index=image_index,
                    user_id=user_id,
                    page=page,
                ),
            ),
            button_data(
                text=f"{em.get_emoji('BACK_arrow')} Back to images",
                callback_data=build_page_callback_data(
                    prefix=IMAGES_PAGE_CALLBACK_PREFIX,
                    page=max(1, page),
                    user_id=user_id,
                ),
            ),
            button_data(
                text="Check updates",
                callback_data=f"__check_updates__:{user_id}",
            ),
        ]
    )


def render_image_details(
    *,
    image_index: int,
    page: int,
    user_id: int,
) -> tuple[str, InlineKeyboardMarkup] | None:
    image_data = _get_image_details_data(image_index=image_index)
    if image_data is None:
        return None

    text = _render_image_details_text(image_data)
    if len(text) > MAX_TELEGRAM_MESSAGE_LENGTH:
        fallback_image = _compact_image(
            image_data,
            max_text_length=MAX_TEXT_FIELD_LENGTH,
            max_list_items=max(1, MAX_LIST_FIELD_ITEMS // 2),
            max_list_item_length=MAX_LIST_ITEM_LENGTH,
            max_label_items=max(1, MAX_LABEL_ITEMS // 2),
            max_label_key_length=MAX_LABEL_KEY_LENGTH,
            max_label_value_length=MAX_LABEL_VALUE_LENGTH,
        )
        text = _render_image_details_text(fallback_image)

    if len(text) > MAX_TELEGRAM_MESSAGE_LENGTH:
        text = (
            f"{em.get_emoji('warning')} <b>Image details are too large for Telegram.</b>\n"
            f"{em.get_emoji('thought_balloon')} Try reviewing this image locally with Docker CLI."
        )

    keyboard = _build_image_details_keyboard(
        image_index=image_index,
        page=page,
        user_id=user_id,
    )
    return text, keyboard


def _compact_image_history_entries(
    history: list[dict[str, Any]],
) -> tuple[list[dict[str, str]], int]:
    compact_rows: list[dict[str, str]] = []
    for row in history[:DETAIL_MAX_HISTORY_ITEMS]:
        compact_rows.append(
            {
                "id": _truncate_text(row.get("id", "N/A"), max_length=24),
                "created": _truncate_text(row.get("created", "N/A"), max_length=48),
                "created_by": _truncate_text(
                    row.get("created_by", "N/A"),
                    max_length=180,
                ),
                "size": _truncate_text(row.get("size", "N/A"), max_length=48),
                "comment": _truncate_text(row.get("comment", ""), max_length=120),
            }
        )

    hidden_count = max(0, len(history) - len(compact_rows))
    return compact_rows, hidden_count


def _render_image_history_text(
    *,
    image_name: str,
    image_id: str,
    history: list[dict[str, Any]],
) -> str:
    rows, hidden_count = _compact_image_history_entries(history)
    return Compiler.quick_render(
        template_name="d_image_history_info.jinja2",
        context={
            "image_name": _truncate_text(image_name, max_length=160),
            "image_id": _truncate_text(image_id, max_length=64),
            "layers": rows,
            "layers_count": len(history),
            "hidden_layers_count": hidden_count,
            "emojis": _get_images_emojis(),
        },
    )


def _compact_image_usage_rows(
    containers: list[dict[str, Any]],
) -> tuple[list[dict[str, str]], int]:
    rows: list[dict[str, str]] = []
    for item in containers[:DETAIL_MAX_USAGE_ITEMS]:
        rows.append(
            {
                "name": _truncate_text(item.get("name", "N/A"), max_length=64),
                "id": _truncate_text(item.get("id", "N/A"), max_length=24),
                "status": _truncate_text(item.get("status", "unknown"), max_length=32),
                "started_at": _truncate_text(
                    item.get("started_at", "N/A"),
                    max_length=48,
                ),
            }
        )

    hidden_count = max(0, len(containers) - len(rows))
    return rows, hidden_count


def _render_image_usage_text(
    *,
    image_name: str,
    image_id: str,
    usage: dict[str, Any],
) -> str:
    raw_containers = usage.get("containers", [])
    containers = raw_containers if isinstance(raw_containers, list) else []
    rows, hidden_count = _compact_image_usage_rows(containers)
    return Compiler.quick_render(
        template_name="d_image_usage_info.jinja2",
        context={
            "image_name": _truncate_text(image_name, max_length=160),
            "image_id": _truncate_text(image_id, max_length=64),
            "containers": rows,
            "containers_count": _safe_positive_int(usage.get("containers_count")),
            "running_count": _safe_positive_int(usage.get("running_count")),
            "stopped_count": _safe_positive_int(usage.get("stopped_count")),
            "hidden_containers_count": hidden_count,
            "emojis": _get_images_emojis(),
        },
    )


def _build_image_extra_keyboard(
    *,
    image_index: int,
    page: int,
    user_id: int,
) -> InlineKeyboardMarkup:
    return keyboards.build_inline_keyboard(
        [
            button_data(
                text=f"{em.get_emoji('BACK_arrow')} Back to image details",
                callback_data=build_image_info_callback_data(
                    image_index=image_index,
                    user_id=user_id,
                    page=page,
                ),
            ),
            button_data(
                text=f"{em.get_emoji('BACK_arrow')} Back to images",
                callback_data=build_page_callback_data(
                    prefix=IMAGES_PAGE_CALLBACK_PREFIX,
                    page=max(1, page),
                    user_id=user_id,
                ),
            ),
        ]
    )


def render_image_extra_info(
    *,
    action: str,
    image_index: int,
    page: int,
    user_id: int,
) -> tuple[str, InlineKeyboardMarkup] | None:
    image = _get_image_raw_data(image_index=image_index)
    if image is None:
        return None

    image_name = str(image.get("name", "N/A"))
    image_id = str(image.get("id", "N/A"))

    if action == "history":
        history = get_image_history(image_id)
        text = _render_image_history_text(
            image_name=image_name,
            image_id=image_id,
            history=history,
        )
    elif action == "usage":
        usage = get_image_usage(image_id)
        text = _render_image_usage_text(
            image_name=image_name,
            image_id=image_id,
            usage=usage,
        )
    else:
        return None

    if len(text) > MAX_TELEGRAM_MESSAGE_LENGTH:
        text = (
            f"{em.get_emoji('warning')} <b>Image details are too large for Telegram.</b>\n"
            f"{em.get_emoji('thought_balloon')} Try opening another section."
        )

    keyboard = _build_image_extra_keyboard(
        image_index=image_index,
        page=page,
        user_id=user_id,
    )
    return text, keyboard


def render_images_page(
    *,
    page: int,
    user_id: int,
) -> tuple[str, InlineKeyboardMarkup]:
    """Build paginated images text and keyboard for requested page."""
    images = _load_images_data()

    prepared_images = _prepare_images_for_listing(images)
    text, safe_page, total_pages, page_items, start_index = (
        _render_paginated_images_text(
            prepared_images,
            page=page,
        )
    )
    keyboard = _build_images_keyboard(
        page=safe_page,
        total_pages=total_pages,
        user_id=user_id,
        page_items=page_items,
        start_index=start_index,
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
            chat_id=message.chat.id,
            error=str(error),
            error_type=type(error).__name__,
        )
        raise exceptions.HandlingException(
            ErrorContext(
                message="Images handler error",
                error_code="HAND_010",
                metadata={"exception": str(error)},
            )
        ) from error
