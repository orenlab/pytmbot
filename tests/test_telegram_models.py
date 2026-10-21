from __future__ import annotations

from ipaddress import ip_network

import pytest

import pytmbot.models.telegram_models as telegram_models_module
from pytmbot.models.telegram_models import (
    TelegramIPValidator,
    is_additional_range_too_wide,
)


def test_telegram_ip_validator_accepts_known_ranges_and_cache_hits() -> None:
    validator = TelegramIPValidator()

    assert validator.is_telegram_ip("91.108.56.1") is True
    assert "91.108.56.1" in validator.validated_ips

    # Cache hit path
    assert validator.is_telegram_ip("91.108.56.1") is True

    assert validator.is_telegram_ip("2001:b28:f23d::1") is True
    assert validator.is_telegram_ip("8.8.8.8") is False


def test_telegram_ip_validator_handles_invalid_ip_and_eviction() -> None:
    validator = TelegramIPValidator()
    validator._MAX_VALIDATED_IPS = 2

    assert validator.is_telegram_ip("not-an-ip") is False

    assert validator.is_telegram_ip("91.108.56.1") is True
    assert validator.is_telegram_ip("91.108.56.2") is True
    assert validator.is_telegram_ip("91.108.56.3") is True

    # First validated IP should be evicted when bound is exceeded.
    assert "91.108.56.1" not in validator.validated_ips
    assert len(validator.validated_ips) == 2


def test_telegram_ip_validator_accepts_additional_ranges() -> None:
    validator = TelegramIPValidator(
        additional_ranges=["10.10.0.0/16", "2001:db8::/32", "invalid-range"]
    )

    assert validator.is_telegram_ip("10.10.1.1") is True
    assert validator.is_telegram_ip("2001:db8::1") is True
    assert validator.is_telegram_ip("10.11.1.1") is False


def test_telegram_ip_validator_unwraps_ipv4_mapped_addresses() -> None:
    validator = TelegramIPValidator()

    assert validator.is_telegram_ip("::ffff:149.154.167.220") is True
    assert validator.is_telegram_ip("::FFFF:959A:A7DC") is True  # same address
    assert validator.is_telegram_ip("::ffff:8.8.8.8") is False
    # The caches hold canonical addresses, so every spelling shares one entry.
    assert validator.validated_ips == {"149.154.167.220"}
    assert validator.rejected_ips == {"8.8.8.8"}
    assert validator.is_telegram_ip("149.154.167.220") is True
    assert validator.is_telegram_ip("8.8.8.8") is False


def test_telegram_ip_validator_skips_too_wide_additional_ranges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[tuple[str, dict[str, object]]] = []

    class _LoggerStub:
        def warning(self, event: str, **context: object) -> None:
            warnings.append((event, context))

    monkeypatch.setattr(telegram_models_module, "logger", _LoggerStub())

    validator = TelegramIPValidator(
        additional_ranges=["0.0.0.0/0", "::/0", "10.0.0.0/15", "2001:db8::/31"]
    )

    assert validator.is_telegram_ip("8.8.8.8") is False
    assert validator.is_telegram_ip("10.1.2.3") is False
    assert validator.is_telegram_ip("2001:db8::1") is False
    assert validator.is_telegram_ip("2606:4700::1") is False
    assert warnings == [
        (
            "bot.models.telegram_models.additional.range.too.wide.warn",
            {"ip_range": ip_range, "min_prefix": min_prefix},
        )
        for ip_range, min_prefix in [
            ("0.0.0.0/0", 16),
            ("::/0", 32),
            ("10.0.0.0/15", 16),
            ("2001:db8::/31", 32),
        ]
    ]


@pytest.mark.parametrize(
    ("network", "too_wide"),
    [
        ("10.0.0.0/15", True),
        ("10.0.0.0/16", False),
        ("2001:db8::/31", True),
        ("2001:db8::/32", False),
    ],
)
def test_additional_range_width_limit(network: str, too_wide: bool) -> None:
    assert is_additional_range_too_wide(ip_network(network)) is too_wide
