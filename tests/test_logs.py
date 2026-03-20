from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from pytmbot.logs import DataMasker, Logger, SecureLoggerFilter

type _LogScalar = str | int | float | bool | None
type _LogValue = _LogScalar | dict[str, "_LogValue"] | list["_LogValue"]
type _LogDict = dict[str, _LogValue]


@dataclass
class _FakeRecord:
    message: str
    extra: _LogDict
    module: str = "main"
    name: str = "pytmbot.main"


def test_data_masker_masks_registered_identifiers() -> None:
    masker = DataMasker()
    masker.add_username("test_user")
    masker.add_user_id(123456789)
    masker.add_chat_id(-4970000716)

    source = "user test_user id 123456789 chat -4970000716"
    sanitized = masker.sanitize_text(source)
    assert "test_user" not in sanitized
    assert "123456789" not in sanitized
    assert "-4970000716" not in sanitized


def test_data_masker_compact_helpers() -> None:
    masker = DataMasker()
    assert masker.mask_token("abcdefghi").startswith("abcd")
    assert masker.mask_username("test_user").startswith("tes")
    assert masker.mask_user_id(123456789) == "12******89"
    assert masker.mask_chat_id(-4970000716).startswith("-497")


def test_secure_logger_filter_normalizes_and_orders_extra() -> None:
    filter_instance = SecureLoggerFilter(DataMasker())
    extra = {
        "component": "bot_launcher",
        "action": "bot.launcher.start",
        "update_type": "message",
        "execution_time_ms": "12.34ms",
        "user_id": 123456789,
        "chat_id": -4970000716,
        "misc": {"a": "b"},
    }
    sanitized = filter_instance._sanitize_extra(
        extra,
        module_name="main",
        logger_name="pytmbot.main",
        message="bot.launcher.start",
    )
    assert sanitized["update"] == "message"
    assert isinstance(sanitized["ms"], float)
    assert "component" not in sanitized
    assert "action" not in sanitized
    assert "user_id" in sanitized
    assert "chat_id" in sanitized


def test_secure_logger_filter_call_sanitizes_record() -> None:
    filter_instance = SecureLoggerFilter(DataMasker())
    record: _LogDict = {
        "message": "token 12345678:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA",
        "extra": {"update_type": "message", "execution_time": "1.2s"},
        "module": "main",
        "name": "pytmbot.main",
    }
    assert filter_instance(record) is True
    message = record.get("message")
    assert isinstance(message, str)
    assert "12345678:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" not in message
    extra = record.get("extra")
    assert isinstance(extra, dict)
    assert extra["ms"] == 1200.0


def test_logger_handler_helpers() -> None:
    assert Logger._handler_event_name("handle_get_logs") == "bot.handler.get_logs"
    assert Logger._handler_log_level(10.0) == "debug"
    assert Logger._handler_log_level(800.0) == "info"
    assert Logger._handler_log_level(3000.0) == "warning"


def test_logger_json_sink_writes_compact_json(
    capsys: pytest.CaptureFixture[str],
) -> None:
    logger = Logger()
    message = SimpleNamespace(
        record={
            "time": SimpleNamespace(
                astimezone=lambda _tz: SimpleNamespace(
                    isoformat=lambda timespec: "2026-01-01T00:00:00.000+00:00"
                )
            ),
            "level": SimpleNamespace(name="INFO"),
            "module": "main",
            "message": "bot.launcher.start",
            "extra": {"trace_id": "abc"},
        }
    )
    logger._json_sink(message)
    output = capsys.readouterr().out
    assert '"msg":"bot.launcher.start"' in output
    assert '"trace_id":"abc"' in output


def test_logger_exception_without_traceback_in_non_debug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = Logger()
    logger._traceback_enabled = False
    calls: list[tuple[str, str, dict[str, object]]] = []

    class _FakeBoundLogger:
        def error(self, message: str, *args: object, **kwargs: object) -> None:
            del args
            calls.append(("error", message, dict(kwargs)))

        def exception(self, message: str, *args: object, **kwargs: object) -> None:
            del args
            calls.append(("exception", message, dict(kwargs)))

    monkeypatch.setattr(Logger, "_get_bound_logger", lambda self: _FakeBoundLogger())

    try:
        raise RuntimeError("boom")
    except RuntimeError:
        logger.exception("bot.test.fail")

    assert len(calls) == 1
    method, message, payload = calls[0]
    assert method == "error"
    assert message == "bot.test.fail"
    assert payload["error_type"] == "RuntimeError"
    assert payload["error"] == "boom"


def test_logger_exception_keeps_explicit_error_payload_in_non_debug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = Logger()
    logger._traceback_enabled = False
    calls: list[tuple[str, str, dict[str, object]]] = []

    class _FakeBoundLogger:
        def error(self, message: str, *args: object, **kwargs: object) -> None:
            del args
            calls.append(("error", message, dict(kwargs)))

        def exception(self, message: str, *args: object, **kwargs: object) -> None:
            del args
            calls.append(("exception", message, dict(kwargs)))

    monkeypatch.setattr(Logger, "_get_bound_logger", lambda self: _FakeBoundLogger())

    try:
        raise ValueError("broken")
    except ValueError:
        logger.exception("bot.test.fail", error={"message": "already-sanitized"})

    assert len(calls) == 1
    method, _, payload = calls[0]
    assert method == "error"
    assert payload["error"] == {"message": "already-sanitized"}
    assert payload["error_type"] == "ValueError"


def test_logger_exception_with_traceback_in_debug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logger = Logger()
    logger._traceback_enabled = True
    calls: list[tuple[str, str, dict[str, object]]] = []

    class _FakeBoundLogger:
        def error(self, message: str, *args: object, **kwargs: object) -> None:
            del args
            calls.append(("error", message, dict(kwargs)))

        def exception(self, message: str, *args: object, **kwargs: object) -> None:
            del args
            calls.append(("exception", message, dict(kwargs)))

    monkeypatch.setattr(Logger, "_get_bound_logger", lambda self: _FakeBoundLogger())

    try:
        raise RuntimeError("boom")
    except RuntimeError:
        logger.exception("bot.test.fail")

    assert len(calls) == 1
    method, message, _ = calls[0]
    assert method == "exception"
    assert message == "bot.test.fail"
