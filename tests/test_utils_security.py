from __future__ import annotations

from dataclasses import dataclass

import pytest

from pytmbot.utils.security import (
    generate_secret_token,
    mask_token_in_message,
    mask_user_id,
    mask_username,
    sanitize_exception,
    sanitize_sensitive_data,
)


@dataclass(frozen=True)
class _FakeSecret:
    value: str

    def get_secret_value(self) -> str:
        return self.value


@dataclass(frozen=True)
class _FakeOutline:
    api_url: list[_FakeSecret]
    cert: list[_FakeSecret]


@dataclass(frozen=True)
class _FakePluginsConfig:
    outline: _FakeOutline


@dataclass(frozen=True)
class _FakeBotToken:
    prod_token: list[_FakeSecret]
    dev_bot_token: list[_FakeSecret]


@dataclass(frozen=True)
class _FakeSettings:
    bot_token: _FakeBotToken
    plugins_config: _FakePluginsConfig


def test_generate_secret_token_validates_length() -> None:
    token = generate_secret_token(16)
    assert isinstance(token, str)
    assert len(token) >= 16
    with pytest.raises(ValueError):
        generate_secret_token(0)


def test_mask_token_in_message_handles_short_and_long_tokens() -> None:
    assert mask_token_in_message("token=abc", "abc") == "token=***"
    masked = mask_token_in_message("token=abcdefghijk", "abcdefghijk", visible_chars=2)
    assert masked.startswith("token=ab")
    assert masked.endswith("jk")
    assert "*" in masked


def test_mask_username_and_user_id() -> None:
    assert mask_username("test_user").startswith("tes")
    assert mask_username("x") == "*"
    assert mask_user_id(123456789).startswith("12")
    assert mask_user_id(None) == "unknown"


def test_sanitize_sensitive_data_masks_explicit_values_and_patterns() -> None:
    source = (
        "token=12345678:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA user test_user id 123456789"
    )
    sanitized = sanitize_sensitive_data(
        source,
        tokens={"12345678:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"},
        usernames={"test_user"},
        user_ids={123456789},
    )
    assert "test_user" not in sanitized
    assert "123456789" not in sanitized
    assert "12345678:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA" not in sanitized


def test_sanitize_exception_masks_known_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_settings = _FakeSettings(
        bot_token=_FakeBotToken(
            prod_token=[_FakeSecret("prod-secret-token")],
            dev_bot_token=[_FakeSecret("dev-secret-token")],
        ),
        plugins_config=_FakePluginsConfig(
            outline=_FakeOutline(
                api_url=[_FakeSecret("https://outline.example/key")],
                cert=[_FakeSecret("outline-cert-secret")],
            )
        ),
    )
    monkeypatch.setattr("pytmbot.utils.security._get_settings", lambda: fake_settings)

    error_text = (
        "failed with prod-secret-token and dev-secret-token "
        "cert outline-cert-secret url https://outline.example/key"
    )
    sanitized = sanitize_exception(Exception(error_text))
    assert "prod-secret-token" not in sanitized
    assert "dev-secret-token" not in sanitized
    assert "outline-cert-secret" not in sanitized
    assert "https://outline.example/key" not in sanitized
