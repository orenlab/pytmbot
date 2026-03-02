#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations


def as_object_dict(value: object) -> dict[str, object]:
    """Return value as dict when possible, otherwise an empty dictionary."""
    return value if isinstance(value, dict) else {}


def to_float(
    value: object,
    default: float = 0.0,
    *,
    strip_percent: bool = False,
) -> float:
    """Safely convert arbitrary values to float with configurable fallback."""
    if isinstance(value, bool):
        return float(int(value))
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        candidate = value.strip()
        if strip_percent:
            candidate = candidate.rstrip("%").strip()
        if not candidate:
            return default
        try:
            return float(candidate)
        except ValueError:
            return default
    return default


def to_float_strict(value: object) -> float:
    """Convert value to float or raise TypeError for unsupported types."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        return float(value.strip())
    raise TypeError(f"Unsupported numeric type: {type(value).__name__}")


def to_int(
    value: object,
    default: int = 0,
    *,
    allow_float_string: bool = False,
    strip_percent: bool = False,
) -> int:
    """Safely convert arbitrary values to int with strict/lenient string mode."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        candidate = value.strip()
        if strip_percent:
            candidate = candidate.rstrip("%").strip()
        if not candidate:
            return default
        try:
            return int(candidate)
        except ValueError:
            if not allow_float_string:
                return default
            try:
                return int(float(candidate))
            except ValueError:
                return default
    return default
