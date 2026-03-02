from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

import pytmbot.exceptions as exceptions_module
from pytmbot.exceptions import BaseBotException, ErrorContext, TelebotExceptionHandler

type _LogValue = str | int | float | bool | None


@dataclass
class _StubLogger:
    events: list[str]

    def opt(self, **_kwargs: _LogValue) -> _StubLogger:
        self.events.append("opt")
        return self

    def bind(self, **_kwargs: _LogValue) -> _StubLogger:
        self.events.append("bind")
        return self

    def debug(self, _message: str, **_kwargs: _LogValue) -> None:
        self.events.append("debug")

    def error(self, _message: str, **_kwargs: _LogValue) -> None:
        self.events.append("error")


def test_error_context_to_dict_and_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "pytmbot.exceptions.sanitize_exception",
        lambda exc: f"sanitized:{exc}",
    )
    context = ErrorContext(
        message="raw",
        error_code="ERR",
        metadata={"token": "secret"},
    )
    assert context.to_dict()["error_code"] == "ERR"
    sanitized = context.sanitized()
    assert sanitized.message.startswith("sanitized:")
    token_value = sanitized.metadata.get("token")
    assert isinstance(token_value, str)
    assert token_value.startswith("sanitized:")


def test_base_exception_exposes_sanitized_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pytmbot.exceptions.sanitize_exception",
        lambda exc: f"safe:{exc}",
    )
    exc = BaseBotException("boom")
    assert exc.sanitized_message().startswith("safe:")
    assert exc.sanitized_context().message.startswith("safe:")


def test_telebot_exception_handler_debug_path(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubLogger(events=[])
    monkeypatch.setattr(exceptions_module, "logger", stub)
    monkeypatch.setattr(
        exceptions_module,
        "parse_cli_args",
        lambda: SimpleNamespace(log_level="DEBUG"),
    )
    monkeypatch.setattr(
        exceptions_module,
        "sanitize_exception",
        lambda exc: str(exc),
    )

    handler = TelebotExceptionHandler()
    result = handler.handle(BaseBotException("x"))
    assert result is True
    assert "debug" in stub.events


def test_telebot_exception_handler_info_path(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _StubLogger(events=[])
    monkeypatch.setattr(exceptions_module, "logger", stub)
    monkeypatch.setattr(
        exceptions_module,
        "parse_cli_args",
        lambda: SimpleNamespace(log_level="INFO"),
    )

    handler = TelebotExceptionHandler()
    result = handler.handle(Exception("plain error"))
    assert result is True
    assert "error" in stub.events
