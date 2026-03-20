#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache

from humanize import naturalsize as humanize_naturalsize

from pytmbot.parsers._types import TemplateValue
from pytmbot.utils import to_float_strict


def format_timestamp(value: TemplateValue) -> str:
    """
    Format a timestamp into human-readable string with error recovery.

    Args:
        value: Timestamp in ISO 8601 format, integer (milliseconds), or other

    Returns:
        str: Formatted timestamp as '%d-%m-%Y %H:%M:%S' or error message
    """
    try:
        match value:
            case str() if value:
                try:
                    iso_value = value.strip()
                    if iso_value.endswith("Z"):
                        iso_value = f"{iso_value[:-1]}+00:00"
                    dt = datetime.fromisoformat(iso_value)
                except (ValueError, TypeError):
                    # Try parsing as unix timestamp string
                    try:
                        timestamp = float(value)
                        dt = datetime.fromtimestamp(
                            timestamp / 1000 if timestamp > 1e10 else timestamp
                        )
                    except (ValueError, TypeError):
                        return f"Invalid date: {value}"
            case int() | float():
                # Auto-detect seconds vs milliseconds
                timestamp = float(value)
                if timestamp > 1e10:  # Likely milliseconds
                    dt = datetime.fromtimestamp(timestamp / 1000)
                else:  # Likely seconds
                    dt = datetime.fromtimestamp(timestamp)
            case _:
                return f"Unsupported timestamp type: {type(value).__name__}"

        return dt.strftime("%d-%m-%Y %H:%M:%S")

    except (ValueError, TypeError, OverflowError) as e:
        return f"Date error: {str(e)[:50]}"


@lru_cache(maxsize=128)
def format_bytes(value: TemplateValue) -> str:
    """
    Format bytes into human-readable format with caching and error recovery.

    Args:
        value: Size in bytes (int, float, or convertible)

    Returns:
        str: Formatted size (e.g., "1.5 GB") or error message
    """
    try:
        if isinstance(value, str):
            cleaned_value = value.strip().lower()
            for suffix in ("bytes", "byte", "kb", "mb", "gb", "tb", "pb", "b"):
                cleaned_value = cleaned_value.removesuffix(suffix).strip()
            size_value = int(float(cleaned_value))
        else:
            size_value = int(to_float_strict(value))

        formatted = humanize_naturalsize(max(0, size_value), binary=False)
        return (
            formatted.replace(" Bytes", " B")
            .replace(" Byte", " B")
            .replace(" kB", " KB")
        )

    except (ValueError, TypeError, OverflowError):
        return f"Invalid size: {value}"


def format_duration(value: TemplateValue) -> str:
    """
    Format duration in seconds to human-readable format with error recovery.

    Args:
        value: Duration in seconds (int, float, or convertible)

    Returns:
        str: Formatted duration (e.g., "2h 30m 45s") or error message
    """
    try:
        seconds = to_float_strict(value)

        if seconds < 0:
            return "0s"

        # Convert to int for calculations
        total_seconds = int(seconds)

        if total_seconds < 60:
            return f"{total_seconds}s"
        elif total_seconds < 3600:
            minutes = total_seconds // 60
            secs = total_seconds % 60
            return f"{minutes}m {secs}s" if secs else f"{minutes}m"
        elif total_seconds < 86400:
            hours = total_seconds // 3600
            minutes = (total_seconds % 3600) // 60
            return f"{hours}h {minutes}m" if minutes else f"{hours}h"
        else:
            days = total_seconds // 86400
            hours = (total_seconds % 86400) // 3600
            return f"{days}d {hours}h" if hours else f"{days}d"

    except (ValueError, TypeError, OverflowError):
        return f"Invalid duration: {value}"


__all__ = [
    "format_timestamp",
    "format_bytes",
    "format_duration",
]
