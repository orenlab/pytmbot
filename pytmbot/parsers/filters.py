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


def format_percentage(value: TemplateValue, decimals: int = 1) -> str:
    """
    Format number as percentage with error recovery.

    Args:
        value: Numeric value (0.0 to 1.0 or 0 to 100)
        decimals: Number of decimal places (0-3)

    Returns:
        str: Formatted percentage (e.g., "75.5%") or error message
    """
    try:
        num_value = to_float_strict(value)

        # Clamp decimals to reasonable range
        decimals = max(0, min(3, int(decimals)))

        # Auto-detect if value is already a percentage (> 1) or fraction (0-1)
        if num_value > 1:
            percentage = min(num_value, 999.9)  # Cap at 999.9%
        else:
            percentage = num_value * 100

        return f"{percentage:.{decimals}f}%"

    except (ValueError, TypeError, OverflowError):
        return f"Invalid percentage: {value}"


def truncate_string(
    value: TemplateValue, max_length: int = 50, suffix: str = "..."
) -> str:
    """
    Truncate string to maximum length with suffix.

    Args:
        value: Value to truncate (will be converted to string)
        max_length: Maximum length including suffix
        suffix: Suffix to add when truncating

    Returns:
        str: Truncated string
    """
    try:
        text = str(value) if value is not None else ""
        max_length = max(len(suffix), int(max_length))  # Ensure suffix fits

        if len(text) <= max_length:
            return text

        return text[: max_length - len(suffix)] + suffix

    except (ValueError, TypeError):
        return str(value)[:max_length] if value is not None else ""


def format_uptime(value: TemplateValue) -> str:
    """
    Format uptime from seconds into human-readable format.

    Args:
        value: Uptime in seconds

    Returns:
        str: Human-readable uptime (e.g., "5 days, 3 hours")
    """
    try:
        seconds = int(to_float_strict(value))

        if seconds < 0:
            return "0 seconds"

        if seconds < 60:
            return f"{seconds} second{'s' if seconds != 1 else ''}"
        elif seconds < 3600:
            minutes = seconds // 60
            return f"{minutes} minute{'s' if minutes != 1 else ''}"
        elif seconds < 86400:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            if minutes:
                return f"{hours} hour{'s' if hours != 1 else ''}, {minutes} minute{'s' if minutes != 1 else ''}"
            return f"{hours} hour{'s' if hours != 1 else ''}"
        else:
            days = seconds // 86400
            hours = (seconds % 86400) // 3600
            if hours:
                return f"{days} day{'s' if days != 1 else ''}, {hours} hour{'s' if hours != 1 else ''}"
            return f"{days} day{'s' if days != 1 else ''}"

    except (ValueError, TypeError, OverflowError):
        return f"Invalid uptime: {value}"


def safe_format(value: TemplateValue, format_type: str = "str") -> str:
    """
    Safe formatting with fallback for any value.

    Args:
        value: Value to format
        format_type: Type of formatting ('str', 'int', 'float')

    Returns:
        str: Safely formatted value
    """
    if value is None:
        return ""

    try:
        match format_type.lower():
            case "int":
                return str(int(to_float_strict(value)))
            case "float":
                return f"{to_float_strict(value):.2f}"
            case "bool":
                return "Yes" if bool(value) else "No"
            case _:  # Default to string
                return str(value)

    except (ValueError, TypeError, OverflowError):
        return str(value) if value is not None else ""


def capitalize_words(value: TemplateValue) -> str:
    """
    Capitalize each word in a string safely.

    Args:
        value: String to capitalize

    Returns:
        str: Capitalized string
    """
    try:
        text = str(value) if value is not None else ""
        return " ".join(word.capitalize() for word in text.split())
    except (AttributeError, TypeError):
        return str(value) if value is not None else ""


__all__ = [
    "format_timestamp",
    "format_bytes",
    "format_duration",
    "format_percentage",
    "format_uptime",
    "truncate_string",
    "safe_format",
    "capitalize_words",
]
