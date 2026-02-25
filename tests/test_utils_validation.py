from __future__ import annotations

from pytmbot.utils.validation import (
    is_bot_development,
    is_new_name_valid,
    is_valid_totp_code,
)


def test_is_new_name_valid_reflects_current_length_contract() -> None:
    assert is_new_name_valid("a") is True
    assert is_new_name_valid("a" * 64) is True
    assert is_new_name_valid("abc") is True
    assert is_new_name_valid(" ") is False


def test_is_valid_totp_code_accepts_only_6_digits() -> None:
    assert is_valid_totp_code("123456") is True
    assert is_valid_totp_code("12345") is False
    assert is_valid_totp_code("12a456") is False


def test_is_bot_development_based_on_version_length() -> None:
    assert is_bot_development("0.3.0-dev") is True
    assert is_bot_development("0.2.2") is False
