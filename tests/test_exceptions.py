from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import patch

import pytest
import requests
import urllib3.exceptions
from telebot import TeleBot
from telebot.apihelper import ApiHTTPException, ApiTelegramException

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


def _quiet_handler(monkeypatch: pytest.MonkeyPatch) -> TelebotExceptionHandler:
    monkeypatch.setattr(exceptions_module, "logger", _StubLogger(events=[]))
    monkeypatch.setattr(
        exceptions_module,
        "parse_cli_args",
        lambda: SimpleNamespace(log_level="INFO"),
    )
    return TelebotExceptionHandler()


def _api_error(error_code: int) -> ApiTelegramException:
    constructor = cast(Callable[..., ApiTelegramException], ApiTelegramException)
    return constructor(
        "getUpdates",
        SimpleNamespace(status_code=error_code, text="error"),
        {"error_code": error_code, "description": "error"},
    )


def _http_error(method: str, status_code: int, reason: str) -> ApiHTTPException:
    constructor = cast(Callable[..., ApiHTTPException], ApiHTTPException)
    return constructor(
        method,
        SimpleNamespace(status_code=status_code, reason=reason, text=""),
    )


def test_handler_leaves_immediate_telegram_outages_to_library_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = _quiet_handler(monkeypatch)

    for error_code in (409, 429, 500, 502, 503, 504):
        assert handler.handle(_api_error(error_code)) is False


def test_handler_consumes_client_errors_that_must_not_pause_polling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = _quiet_handler(monkeypatch)

    for error_code in (400, 401, 403, 404):
        assert handler.handle(_api_error(error_code)) is True


def test_handler_leaves_raw_gateway_http_errors_to_library_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = _quiet_handler(monkeypatch)
    gateway = _http_error("getUpdates", 502, "Bad Gateway")
    client = _http_error("sendMessage", 400, "Bad Request")

    assert handler.handle(gateway) is False
    assert handler.handle(client) is True


def test_handler_leaves_transport_failures_to_the_launcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = _quiet_handler(monkeypatch)

    assert (
        handler.handle(
            requests.exceptions.ReadTimeout(
                "HTTPSConnectionPool(host='api.telegram.org', port=443): "
                "Read timed out. (read timeout=65)"
            )
        )
        is False
    )
    assert (
        handler.handle(
            requests.exceptions.ConnectionError(
                "('Connection aborted.', ConnectionResetError(104, "
                "'Connection reset by peer'))"
            )
        )
        is False
    )
    assert (
        handler.handle(urllib3.exceptions.ProtocolError("Connection aborted.")) is False
    )


def _drive_polling(
    handler: TelebotExceptionHandler, script: list[object]
) -> tuple[list[float], BaseException | None]:
    """Run TeleBot.polling() against a scripted getUpdates, with sleep recorded."""
    sleeps: list[float] = []
    steps = list(script)
    bot = TeleBot(
        "1:probe", threaded=True, exception_handler=handler, skip_pending=False
    )
    cast(Any, bot)._user = SimpleNamespace(username="probe", id=1)
    stop_polling = cast(Callable[[], None], bot.stop_polling)

    def get_updates(*_args: object, **_kwargs: object) -> list[object]:
        step = steps.pop(0)
        if step == "stop":
            stop_polling()
            return []
        if step == "ok":
            return []
        if step == "timeout":
            raise requests.exceptions.ReadTimeout("read timeout=65")
        if isinstance(step, int):
            raise _api_error(step)
        raise AssertionError(step)

    def record_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    raised: BaseException | None = None
    with (
        patch("telebot.time.sleep", record_sleep),
        patch("telebot.apihelper.get_updates", get_updates),
    ):
        try:
            bot.polling(
                non_stop=True,
                timeout=30,
                long_polling_timeout=60,
                logger_level=logging.NOTSET,
            )
        except BaseException as error:
            raised = error
        finally:
            stop_polling()
    return sleeps, raised


def test_polling_defers_gateway_errors_and_releases_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logging.getLogger("TeleBot").setLevel(logging.CRITICAL)
    handler = _quiet_handler(monkeypatch)

    gateway_sleeps, gateway_error = _drive_polling(
        handler, [502, 502, 502, "ok", 502, "stop"]
    )
    assert gateway_error is None
    # Doubles while the gateway is down, then a successful poll resets it.
    assert gateway_sleeps == [0.25, 0.5, 1.0, 0.25]

    capped_sleeps, capped_error = _drive_polling(handler, [502] * 9 + ["stop"])
    assert capped_error is None
    assert capped_sleeps == [0.25, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0, 32.0, 60.0]

    timeout_sleeps, timeout_error = _drive_polling(handler, ["timeout", "stop"])
    assert timeout_sleeps == []
    assert isinstance(timeout_error, requests.exceptions.ReadTimeout)

    client_sleeps, client_error = _drive_polling(handler, [400, 400, "stop"])
    assert client_error is None
    assert client_sleeps == [0.25, 0.25]
