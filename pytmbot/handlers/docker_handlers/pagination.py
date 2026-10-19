#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pytmbot.handlers.docker_handlers.callback_data import (
    build_callback_data,
    is_valid_container_ref,
    parse_callback_user_id,
)
from pytmbot.utils.rich_html import measure_rich_html

CONTAINER_FULL_INFO_CALLBACK_PREFIX = "__get_full__"


def fits_rich_message(html: str) -> bool:
    """Return True when rendered rich HTML fits Telegram rich-message limits."""
    return measure_rich_html(html).fits


def build_page_footer(
    *,
    page: int,
    total_pages: int,
    shown: int,
    total_items: int,
    noun: str,
) -> str:
    """Render the rich pagination footer shared by Docker list screens."""
    return (
        f"<footer>Page {page}/{total_pages} · Shown: {shown} · "
        f"Total {noun}: {total_items}</footer>"
    )


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

    ``container_ref`` is the short container ID and is never case-folded.

    Raises:
        ValueError: If the reference is invalid or the payload is too long.
    """
    if not is_valid_container_ref(container_ref):
        raise ValueError("Invalid container reference")
    if page is None:
        return build_callback_data(prefix, container_ref, int(user_id))
    return build_callback_data(prefix, container_ref, int(user_id), max(1, int(page)))


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

    container_ref = parts[1]
    user_id = parse_callback_user_id(parts[2])
    if user_id is None or not is_valid_container_ref(container_ref):
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
