#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

MAX_TELEGRAM_MESSAGE_LENGTH = 4096
CONTAINER_FULL_INFO_CALLBACK_PREFIX = "__get_full__"


@dataclass(frozen=True, slots=True)
class PaginationWindow[T]:
    """A normalized window of paginated data."""

    items: list[T]
    page: int
    total_pages: int
    total_items: int
    page_size: int


def paginate_items[T](
    items: Sequence[T],
    page: int,
    page_size: int,
) -> PaginationWindow[T]:
    """
    Build a safe pagination window for sequence data.

    Page numbers are 1-based.
    """
    normalized_size = max(1, int(page_size))
    total_items = len(items)
    total_pages = max(1, (total_items + normalized_size - 1) // normalized_size)
    normalized_page = max(1, min(int(page), total_pages))

    start = (normalized_page - 1) * normalized_size
    end = start + normalized_size
    page_items = list(items[start:end])

    return PaginationWindow(
        items=page_items,
        page=normalized_page,
        total_pages=total_pages,
        total_items=total_items,
        page_size=normalized_size,
    )


def parse_page_callback_data(
    callback_data: str,
    *,
    prefix: str,
) -> tuple[int, int] | None:
    """
    Parse callback payload in format: '{prefix}:{page}:{user_id}'.
    """
    parts = callback_data.split(":")
    if len(parts) != 3 or parts[0] != prefix:
        return None

    try:
        page = int(parts[1])
        user_id = int(parts[2])
    except (TypeError, ValueError):
        return None

    if page < 1:
        return None

    return page, user_id


def build_page_callback_data(*, prefix: str, page: int, user_id: int) -> str:
    """Build callback payload for pagination navigation."""
    safe_page = max(1, int(page))
    return f"{prefix}:{safe_page}:{int(user_id)}"


def build_container_full_info_callback_data(
    *,
    container_ref: str,
    user_id: int,
    page: int | None = None,
    prefix: str = CONTAINER_FULL_INFO_CALLBACK_PREFIX,
) -> str:
    """
    Build callback payload for container full-info actions.

    Supported format:
    - '{prefix}:{container_ref}:{user_id}'
    - '{prefix}:{container_ref}:{user_id}:{page}'
    """
    safe_container_ref = container_ref.strip().lower()
    if page is None:
        return f"{prefix}:{safe_container_ref}:{int(user_id)}"
    safe_page = max(1, int(page))
    return f"{prefix}:{safe_container_ref}:{int(user_id)}:{safe_page}"


def parse_container_full_info_callback_data(
    callback_data: str,
    *,
    prefix: str = CONTAINER_FULL_INFO_CALLBACK_PREFIX,
) -> tuple[str, int, int | None] | None:
    """
    Parse full-info callback payload.

    Accepted payloads:
    - '{prefix}:{container_ref}:{user_id}'
    - '{prefix}:{container_ref}:{user_id}:{page}'
    """
    parts = callback_data.split(":")
    if len(parts) not in (3, 4):
        return None
    if parts[0] != prefix:
        return None

    container_ref = parts[1].strip().lower()
    if not container_ref:
        return None

    try:
        user_id = int(parts[2])
    except (TypeError, ValueError):
        return None

    if len(parts) == 3:
        return container_ref, user_id, None

    try:
        page = int(parts[3])
    except (TypeError, ValueError):
        return None
    if page < 1:
        return None

    return container_ref, user_id, page
