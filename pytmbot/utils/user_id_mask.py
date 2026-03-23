#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from typing import Final

USER_ID_VISIBLE_EDGE_DIGITS: Final[int] = 2
USER_ID_MASK_CORE: Final[str] = "******"


def mask_user_id_value(
    user_id: int | None,
    *,
    unknown_placeholder: str = "unknown",
) -> str:
    """
    Mask user identifier using a fixed shape: ``12******89``.

    This keeps exactly the first two and last two digits visible and inserts
    six asterisks between them, producing a consistent 10-character format
    for normal Telegram numeric identifiers.
    """
    if user_id is None:
        return unknown_placeholder

    user_id_str = str(abs(user_id))
    if len(user_id_str) < USER_ID_VISIBLE_EDGE_DIGITS * 2:
        return "*" * len(user_id_str)

    return (
        f"{user_id_str[:USER_ID_VISIBLE_EDGE_DIGITS]}"
        f"{USER_ID_MASK_CORE}"
        f"{user_id_str[-USER_ID_VISIBLE_EDGE_DIGITS:]}"
    )
