from __future__ import annotations

from pytmbot.models.telegram_models import TelegramIPValidator


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
