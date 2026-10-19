from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

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


_TOKEN = "123456789:AAH4ExampleSecretTokenPart0123456789"


def _callback(
    *,
    username: str | None = None,
    first_name: str | None = None,
    last_name: str | None = None,
) -> _FakeCallback:
    return _FakeCallback(
        from_user=_FakeUser(
            id=123456789,
            username=username,
            first_name=first_name,
            last_name=last_name,
        ),
        message=_FakeMessage(from_user=_FakeUser(id=987654321), text=None),
    )


def test_sanitize_logs_removes_ansi_and_masks_only_the_token() -> None:
    callback = _callback(username="test_user", first_name="Max", last_name="User")
    logs = (
        "\x1b[31mtest_user Max User 123456789 987654321 "
        f"token={_TOKEN} secret={_TOKEN.split(':', 1)[1]}\x1b[0m"
    )
    sanitized = telegram_utils.sanitize_logs(logs, callback, _TOKEN)  # type: ignore[arg-type]
    assert "\x1b" not in sanitized
    assert _TOKEN not in sanitized
    assert _TOKEN.split(":", 1)[1] not in sanitized
    # Ordinary words and ids are not secrets.
    assert "test_user Max User 123456789 987654321" in sanitized


def test_sanitize_logs_keeps_words_matching_the_presser_name() -> None:
    callback = _callback(first_name="Max", username="nginx")
    logs = "Max connections reached; MaxRequestWorkers=150; nginx started"
    assert telegram_utils.sanitize_logs(logs, callback, _TOKEN) == logs  # type: ignore[arg-type]


def test_sanitize_logs_strips_osc_and_other_escape_sequences() -> None:
    logs = (
        "\x1b]0;window title\x07plain "
        "\x1b]8;;https://example.com\x1b\\link\x1b]8;;\x1b\\ "
        "\x1bPdevice-control\x1b\\"
        "\x1b(Bcharset \x1b7saved\x1b8 \x9b1mc1-csi "
        "bell\x07 null\x00 tab\tnew\nline\r\n"
    )
    sanitized = telegram_utils.sanitize_logs(logs, None, _TOKEN)
    assert sanitized == ("plain link charset saved c1-csi bell null tab\tnew\nline\r\n")


def test_sanitize_logs_handles_none_and_bytes() -> None:
    assert telegram_utils.sanitize_logs(None, None, _TOKEN) == ""
    assert telegram_utils.sanitize_logs(b"ok \xff", None, _TOKEN) == "ok \ufffd"


def test_sanitize_logs_handles_non_string_input() -> None:
    callback = SimpleNamespace(from_user=None, message=None)
    sanitized = telegram_utils.sanitize_logs(1234, callback, "TOKEN")  # type: ignore[arg-type]
    assert sanitized == "1234"


def test_sanitize_logs_masks_token_inside_longer_words() -> None:
    sanitized = telegram_utils.sanitize_logs("TOKEN TOKEN_EXT", None, "TOKEN")
    assert sanitized == "***** *****_EXT"
