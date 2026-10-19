#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.

Callback payload helpers for Docker inline keyboards.

Every container button carries the 12-character short container ID exactly as
Docker reports it (never a lower-cased name) and, as its last segment, the id
of the user the button belongs to. Payloads are built with an explicit check
against Telegram's 64-byte limit instead of being truncated.
"""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass
from typing import Final

TELEGRAM_CALLBACK_DATA_MAX_BYTES: Final[int] = 64
CALLBACK_SEPARATOR: Final[str] = ":"
CONTAINER_SHORT_ID_LENGTH: Final[int] = 12
MAX_CONTAINER_REF_LENGTH: Final[int] = 64

MANAGE_CALLBACK_PREFIX: Final[str] = "__manage__"
START_CALLBACK_PREFIX: Final[str] = "__start__"
STOP_CALLBACK_PREFIX: Final[str] = "__stop__"
RESTART_CALLBACK_PREFIX: Final[str] = "__restart__"
CONFIRM_STOP_CALLBACK_PREFIX: Final[str] = "__stop_confirm__"
CONFIRM_RESTART_CALLBACK_PREFIX: Final[str] = "__restart_confirm__"
LOGS_CALLBACK_PREFIX: Final[str] = "__get_logs__"
CONTAINER_EXTRA_CALLBACK_PREFIX: Final[str] = "__container_extra__"

# Buttons that change container state; never offered again as a "return" target.
CONTAINER_ACTION_CALLBACK_PREFIXES: Final[frozenset[str]] = frozenset(
    {
        START_CALLBACK_PREFIX,
        STOP_CALLBACK_PREFIX,
        RESTART_CALLBACK_PREFIX,
        CONFIRM_STOP_CALLBACK_PREFIX,
        CONFIRM_RESTART_CALLBACK_PREFIX,
    }
)
_RETURN_LABELS: Final[dict[str, str]] = {
    MANAGE_CALLBACK_PREFIX: "container actions",
    LOGS_CALLBACK_PREFIX: "container logs",
    CONTAINER_EXTRA_CALLBACK_PREFIX: "container details",
}

# Docker container names: [a-zA-Z0-9][a-zA-Z0-9_.-]*; hex IDs match as well.
_CONTAINER_REF_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"[a-zA-Z0-9][a-zA-Z0-9_.-]*"
)
_CONTAINER_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{12,64}")


class CallbackDataTooLongError(ValueError):
    """Raised when a callback payload would exceed Telegram's 64-byte limit."""


def callback_data_size(callback_data: str) -> int:
    """Return the size Telegram counts for callback data (UTF-8 bytes)."""
    return len(callback_data.encode("utf-8"))


def build_callback_data(*parts: str | int) -> str:
    """
    Join callback segments and enforce Telegram's callback size limit.

    Raises:
        ValueError: If a segment is empty or contains the separator.
        CallbackDataTooLongError: If the payload exceeds 64 bytes.
    """
    segments = [str(part) for part in parts]
    if not segments or any(
        not segment or CALLBACK_SEPARATOR in segment for segment in segments
    ):
        raise ValueError("Callback segments must be non-empty and must not contain ':'")

    callback_data = CALLBACK_SEPARATOR.join(segments)
    size = callback_data_size(callback_data)
    if size > TELEGRAM_CALLBACK_DATA_MAX_BYTES:
        raise CallbackDataTooLongError(
            f"Callback data is {size} bytes; Telegram allows "
            f"{TELEGRAM_CALLBACK_DATA_MAX_BYTES}"
        )
    return callback_data


def is_valid_container_ref(container_ref: str) -> bool:
    """Return True for a short/full container ID or a Docker container name."""
    return (
        0 < len(container_ref) <= MAX_CONTAINER_REF_LENGTH
        and _CONTAINER_REF_PATTERN.fullmatch(container_ref) is not None
    )


def container_short_id(raw_id: object) -> str | None:
    """Return the 12-character short form of a Docker container ID, or None."""
    value = str(raw_id).strip() if raw_id is not None else ""
    if _CONTAINER_ID_PATTERN.fullmatch(value) is None:
        return None
    return value[:CONTAINER_SHORT_ID_LENGTH]


def parse_callback_user_id(raw_user_id: str) -> int | None:
    """Parse a positive Telegram user id from a callback segment."""
    if not (raw_user_id.isascii() and raw_user_id.isdigit()):
        return None
    user_id = int(raw_user_id)
    return user_id if user_id > 0 else None


@dataclass(frozen=True, slots=True)
class ContainerCallback:
    """A parsed ``<prefix>:<container ref>:<user id>`` payload."""

    prefix: str
    container_ref: str
    user_id: int


def build_container_callback(prefix: str, container_ref: str, user_id: int) -> str:
    """Build a ``<prefix>:<container ref>:<user id>`` payload."""
    if not is_valid_container_ref(container_ref):
        raise ValueError("Invalid container reference")
    return build_callback_data(prefix, container_ref, int(user_id))


def parse_container_callback(
    callback_data: str | None, *, prefixes: Collection[str]
) -> ContainerCallback | None:
    """Parse ``<prefix>:<container ref>:<user id>`` for one of ``prefixes``."""
    parts = (callback_data or "").split(CALLBACK_SEPARATOR)
    if len(parts) != 3 or parts[0] not in prefixes:
        return None

    prefix, container_ref, raw_user_id = parts
    user_id = parse_callback_user_id(raw_user_id)
    if user_id is None or not is_valid_container_ref(container_ref):
        return None
    return ContainerCallback(
        prefix=prefix, container_ref=container_ref, user_id=user_id
    )


def post_auth_return_callback(callback_data: str) -> str | None:
    """
    Return the callback offered as "Return to ..." once 2FA succeeds.

    State-changing actions (start/stop/restart and their confirmations) are
    replaced by the Manage screen of the same container, so finishing 2FA can
    never repeat an action with a single tap. ``None`` means no safe target.
    """
    prefix, separator, rest = callback_data.partition(CALLBACK_SEPARATOR)
    if prefix not in CONTAINER_ACTION_CALLBACK_PREFIXES:
        return callback_data
    if not separator:
        return None
    target = f"{MANAGE_CALLBACK_PREFIX}{CALLBACK_SEPARATOR}{rest}"
    if callback_data_size(target) > TELEGRAM_CALLBACK_DATA_MAX_BYTES:
        return None
    return target


def post_auth_return_label(callback_data: str) -> str | None:
    """Return a human label for a post-2FA return target, when known."""
    prefix = callback_data.partition(CALLBACK_SEPARATOR)[0]
    return _RETURN_LABELS.get(prefix)
