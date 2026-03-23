#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from typing import Final

MIN_CONTAINER_NAME_LENGTH: Final[int] = 1
MAX_CONTAINER_NAME_LENGTH: Final[int] = 64
MIN_DEV_VERSION_LENGTH: Final[int] = 7


def is_new_name_valid(new_name: str) -> bool:
    if not (MIN_CONTAINER_NAME_LENGTH <= len(new_name) <= MAX_CONTAINER_NAME_LENGTH):
        return False
    if new_name.isspace():
        return False
    return True


def is_valid_totp_code(totp_code: str) -> bool:
    return len(totp_code) == 6 and totp_code.isdigit()


def is_bot_development(app_version: str) -> bool:
    return len(app_version) >= MIN_DEV_VERSION_LENGTH
