from __future__ import annotations

import sys

import pytest

from pytmbot.utils.cli import (
    BotMode,
    CLIError,
    LogFormat,
    LogLevel,
    _str_to_bool,
    _validate_plugins,
    _validate_socket_host,
    parse_cli_args,
)


def test_str_to_bool_accepts_common_values() -> None:
    assert _str_to_bool("true") is True
    assert _str_to_bool("YES") is True
    assert _str_to_bool("1") is True
    assert _str_to_bool("off") is False
    assert _str_to_bool("0") is False


def test_str_to_bool_rejects_invalid_value() -> None:
    with pytest.raises(CLIError):
        _str_to_bool("maybe")


def test_validate_socket_host_accepts_valid_formats() -> None:
    assert _validate_socket_host("127.0.0.1") == "127.0.0.1"
    assert _validate_socket_host("localhost") == "localhost"
    assert _validate_socket_host("my-host:8080") == "my-host:8080"


def test_validate_socket_host_rejects_invalid() -> None:
    with pytest.raises(CLIError):
        _validate_socket_host("bad host with spaces")


def test_validate_plugins_filters_empty_and_keeps_valid() -> None:
    assert _validate_plugins(["plugin_a", "  ", "plugin-b"]) == [
        "plugin_a",
        "plugin-b",
    ]


def test_validate_plugins_rejects_non_string() -> None:
    with pytest.raises(CLIError):
        _validate_plugins(["ok", 1])  # type: ignore[list-item]


def test_parse_cli_args_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    parse_cli_args.cache_clear()
    monkeypatch.setattr(sys, "argv", ["prog"])
    args = parse_cli_args()

    assert args.mode == BotMode.PROD
    assert args.log_level == LogLevel.INFO
    assert args.log_format == LogFormat.JSON
    assert args.plugins == []
    assert args.health_check is False


def test_parse_cli_args_debug_flag_overrides_mode_and_level(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parse_cli_args.cache_clear()
    monkeypatch.setattr(sys, "argv", ["prog", "--debug"])
    args = parse_cli_args()

    assert args.mode == BotMode.DEV
    assert args.log_level == LogLevel.DEBUG
    assert args.log_format == LogFormat.HUMAN


def test_parse_cli_args_rejects_invalid_plugin_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parse_cli_args.cache_clear()
    monkeypatch.setattr(sys, "argv", ["prog", "--plugins", "bad!name"])
    with pytest.raises(CLIError):
        parse_cli_args()
