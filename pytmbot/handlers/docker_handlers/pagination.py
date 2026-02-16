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
