from __future__ import annotations

from dataclasses import dataclass

import pytest

from pytmbot.utils.security import (
    generate_secret_token,
    mask_chat_id,
    mask_token_in_message,
    mask_user_id,
    mask_username,
    mask_webhook_path,
    sanitize_exception,
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
class _FakeInfluxDB:
    url: list[_FakeSecret]
    token: list[_FakeSecret]
    org: list[_FakeSecret]
    bucket: list[_FakeSecret]


@dataclass(frozen=True)
class _FakeBotToken:
    prod_token: list[_FakeSecret]
    dev_bot_token: list[_FakeSecret]


@dataclass(frozen=True)
class _FakeSettings:
    bot_token: _FakeBotToken
    plugins_config: _FakePluginsConfig
    influxdb: _FakeInfluxDB | None = None


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


def test_mask_webhook_path_masks_token_fragment() -> None:
    raw_path = "/webhook/j-MelQvyyAxD7ryabbVX2Q/"
    masked = mask_webhook_path(raw_path)
    assert masked.startswith("/webhook/j-M")
    assert masked.endswith("X2Q/")
    assert "j-MelQvyyAxD7ryabbVX2Q" not in masked
    assert "*" in masked


def test_mask_webhook_path_masks_embedded_url() -> None:
    raw_url = "https://example.com/webhook/AbCdEf1234567890/?x=1"
    masked = mask_webhook_path(raw_url)
    assert "/webhook/AbC" in masked
    assert "AbCdEf1234567890" not in masked
    assert "*" in masked


def test_mask_username_and_user_id() -> None:
    assert mask_username("test_user").startswith("tes")
    assert mask_username("x") == "*"
    assert mask_user_id(123456789) == "12******89"
    assert mask_user_id(None) == "unknown"
    assert mask_chat_id(-4970000716) == "-497****716"
    assert mask_chat_id(None) == "unknown"


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
        influxdb=_FakeInfluxDB(
            url=[_FakeSecret("https://influx.example:8086")],
            token=[_FakeSecret("influx-token-secret")],
            org=[_FakeSecret("influx-org-secret")],
            bucket=[_FakeSecret("influx-bucket-secret")],
        ),
    )
    monkeypatch.setattr("pytmbot.utils.security._get_settings", lambda: fake_settings)

    error_text = (
        "failed with prod-secret-token and dev-secret-token "
        "cert outline-cert-secret url https://outline.example/key "
        "influx https://influx.example:8086 token influx-token-secret "
        "org influx-org-secret bucket influx-bucket-secret"
    )
    sanitized = sanitize_exception(Exception(error_text))
    assert "prod-secret-token" not in sanitized
    assert "dev-secret-token" not in sanitized
    assert "outline-cert-secret" not in sanitized
    assert "https://outline.example/key" not in sanitized
    assert "https://influx.example:8086" not in sanitized
    assert "influx-token-secret" not in sanitized
    assert "influx-org-secret" not in sanitized
    assert "influx-bucket-secret" not in sanitized
