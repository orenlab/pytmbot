from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

import pytmbot.utils.telegram_utils as telegram_utils


@dataclass
class _FakeUser:
    id: int
    username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    language_code: str | None = None
    is_bot: bool | None = None


@dataclass
class _FakeMessage:
    from_user: _FakeUser | None
    text: str | None = None


@dataclass
class _FakeCallback:
    from_user: _FakeUser | None
    message: _FakeMessage | None


def test_get_message_full_info_returns_structured_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_message = _FakeMessage(
        from_user=_FakeUser(
            id=1,
            username="den",
            language_code="ru",
            is_bot=False,
        ),
        text="hello",
    )
    monkeypatch.setattr(telegram_utils, "find_in_args", lambda *_a, **_k: fake_message)
    monkeypatch.setattr(telegram_utils, "find_in_kwargs", lambda *_a, **_k: None)

    info = telegram_utils.get_message_full_info(object())
    assert info.username == "den"
    assert info.user_id == 1
    assert info.text == "hello"


def test_get_inline_message_full_info_returns_defaults_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(telegram_utils, "find_in_args", lambda *_a, **_k: None)
    monkeypatch.setattr(telegram_utils, "find_in_kwargs", lambda *_a, **_k: None)
    info = telegram_utils.get_inline_message_full_info(object())
    assert info.username is None
    assert info.user_id is None


def test_sanitize_logs_removes_ansi_and_masks_sensitive_fields() -> None:
    callback = _FakeCallback(
        from_user=_FakeUser(
            id=123456789,
            username="test_user",
            first_name="Test",
            last_name="User",
        ),
        message=_FakeMessage(
            from_user=_FakeUser(id=123456789),
            text=None,
        ),
    )
    logs = "\x1b[31mtest_user Test User 123456789 TOKEN\x1b[0m"
    sanitized = telegram_utils.sanitize_logs(logs, callback, "TOKEN")  # type: ignore[arg-type]
    assert "\x1b" not in sanitized
    assert "test_user" not in sanitized
    assert "TOKEN" not in sanitized


def test_sanitize_logs_handles_non_string_input() -> None:
    callback = SimpleNamespace(from_user=None, message=None)
    sanitized = telegram_utils.sanitize_logs(1234, callback, "TOKEN")  # type: ignore[arg-type]
    assert sanitized == "1234"


def test_sanitize_logs_masks_overlapping_sensitive_values() -> None:
    callback = _FakeCallback(
        from_user=_FakeUser(
            id=42,
            username="TOKEN_EXT",
            first_name="John",
            last_name="Doe",
        ),
        message=_FakeMessage(
            from_user=_FakeUser(id=42),
            text=None,
        ),
    )
    logs = "TOKEN TOKEN_EXT TOKEN"
    sanitized = telegram_utils.sanitize_logs(logs, callback, "TOKEN")  # type: ignore[arg-type]
    assert "TOKEN_EXT" not in sanitized
    assert "TOKEN" not in sanitized
