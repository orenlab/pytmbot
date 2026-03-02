#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from datetime import datetime

from humanize import (
    naturalsize as humanize_naturalsize,
)
from humanize import (
    naturaltime as humanize_naturaltime,
)


def round_up_tuple(numbers: tuple[float, ...]) -> dict[int, float]:
    return {i: round(num, 2) for i, num in enumerate(numbers)}


def find_in_args[T](args: tuple[object, ...], target_type: type[T]) -> T | None:
    return next((arg for arg in args if isinstance(arg, target_type)), None)


def find_in_kwargs[T](kwargs: dict[str, object], target_type: type[T]) -> T | None:
    return next(
        (value for value in kwargs.values() if isinstance(value, target_type)), None
    )


def set_naturalsize(size: int | float | None) -> str:
    if size is None:
        normalized_size = 0
    elif isinstance(size, bool) or not isinstance(size, (int, float)):
        raise TypeError("size must be int, float, or None")
    else:
        normalized_size = int(size) if size > 0 else 0

    return humanize_naturalsize(normalized_size, binary=True)


def set_naturaltime(timestamp: datetime) -> str:
    return humanize_naturaltime(timestamp)


def split_string_into_octets(
    input_string: str, delimiter: str = ":", octet_index: int = 1
) -> str:
    if not input_string:
        raise ValueError("input_string cannot be empty")
    if not delimiter:
        raise ValueError("delimiter cannot be empty")
    octets = input_string.split(delimiter)
    if not (0 <= octet_index < len(octets)):
        raise IndexError("Octet index out of range")
    return octets[octet_index].lower()
