from __future__ import annotations

from pydantic import SecretStr

from pytmbot.models.settings_model import WebhookConfig


def build_webhook_config(*, trusted_proxy_ips: list[str]) -> WebhookConfig:
    """Create a minimal valid webhook config for validation tests."""
    return WebhookConfig(
        url=[SecretStr("https://example.com")],
        webhook_port=[8443],
        local_port=[8080],
        cert=None,
        cert_key=None,
        trusted_proxy_ips=trusted_proxy_ips,
    )
