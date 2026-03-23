from __future__ import annotations

from pytmbot.parsers.filters import (
    format_bytes,
    format_duration,
    format_timestamp,
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
