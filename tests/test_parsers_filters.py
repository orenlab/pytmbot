from __future__ import annotations

from pytmbot.parsers.filters import (
    capitalize_words,
    format_bytes,
    format_duration,
    format_percentage,
    format_timestamp,
    format_uptime,
    safe_format,
    truncate_string,
)


def test_format_timestamp_supports_iso_and_unix_inputs() -> None:
    assert format_timestamp("2026-02-17T12:00:00Z") == "17-02-2026 12:00:00"
    assert format_timestamp("1700000000").count(":") == 2
    assert format_timestamp(1700000000000).count(":") == 2


def test_format_timestamp_handles_invalid_values() -> None:
    assert format_timestamp("not-a-date").startswith("Invalid date:")
    assert format_timestamp(None).startswith("Unsupported timestamp type:")


def test_format_bytes_normalizes_units_and_handles_errors() -> None:
    assert format_bytes(1024) == "1.0 KB"
    assert format_bytes("2048") == "2.0 KB"
    assert format_bytes(-100) == "0 B"
    assert format_bytes("oops").startswith("Invalid size:")


def test_format_duration_for_common_ranges() -> None:
    assert format_duration(59) == "59s"
    assert format_duration(60) == "1m"
    assert format_duration(125) == "2m 5s"
    assert format_duration(3600) == "1h"
    assert format_duration(90061) == "1d 1h"
    assert format_duration(-1) == "0s"
    assert format_duration("oops").startswith("Invalid duration:")


def test_format_percentage_clamps_and_autodetects_modes() -> None:
    assert format_percentage(0.5) == "50.0%"
    assert format_percentage(42, decimals=0) == "42%"
    assert format_percentage(9999) == "999.9%"
    assert format_percentage(1.234, decimals=10) == "1.234%"
    assert format_percentage("bad").startswith("Invalid percentage:")


def test_truncate_string_and_safe_format_helpers() -> None:
    assert truncate_string("abc", max_length=10) == "abc"
    assert truncate_string("abcdef", max_length=4) == "a..."
    assert truncate_string(None, max_length=4) == ""

    assert safe_format("12.7", "int") == "12"
    assert safe_format("12.75", "float") == "12.75"
    assert safe_format(0, "bool") == "No"
    assert safe_format(1, "bool") == "Yes"
    assert safe_format(None, "str") == ""
    assert safe_format("x", "unknown") == "x"


def test_format_uptime_and_capitalize_words() -> None:
    assert format_uptime(1) == "1 second"
    assert format_uptime(120) == "2 minutes"
    assert format_uptime(3660) == "1 hour, 1 minute"
    assert format_uptime(90000) == "1 day, 1 hour"
    assert format_uptime(-1) == "0 seconds"
    assert format_uptime("bad").startswith("Invalid uptime:")

    assert capitalize_words("hello world") == "Hello World"
    assert capitalize_words(None) == ""
