from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from pydantic import SecretStr, ValidationError

import pytmbot.settings as settings_module
from pytmbot.models.settings_model import WebhookConfig
from pytmbot.settings import (
    _get_config_file_path,
    _get_var_config,
    get_default_auth_keyboard,
    get_default_back_keyboard,
    get_default_bot_commands,
    get_default_docker_keyboard,
    get_default_log_levels,
    get_default_main_keyboard,
    get_default_server_keyboard,
    load_settings_from_yaml,
)


def test_default_settings_factories_return_expected_keys() -> None:
    assert "rocket" in get_default_main_keyboard()
    assert "stethoscope" in get_default_main_keyboard()
    assert "penguin" not in get_default_server_keyboard()
    assert "stethoscope" not in get_default_server_keyboard()
    assert "framed_picture" in get_default_docker_keyboard()
    assert "first_quarter_moon" in get_default_auth_keyboard()
    assert "BACK_arrow" in get_default_back_keyboard()
    assert "/start" in get_default_bot_commands()
    assert "DEBUG" in get_default_log_levels()


def test_get_config_file_path_points_to_project_yaml() -> None:
    config_path = _get_config_file_path()
    assert isinstance(config_path, Path)
    assert config_path == Path(os.environ["PYTMBOT_CONFIG_PATH"]).resolve()


def test_load_settings_from_yaml_reads_current_project_config() -> None:
    settings = load_settings_from_yaml()
    assert settings.bot_token.prod_token
    assert settings.access_control.allowed_user_ids


def test_load_settings_from_yaml_file_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings_module,
        "_get_config_file_path",
        lambda: Path("/tmp/definitely_missing_pytmbot_config.yaml"),
    )
    load_settings_from_yaml.cache_clear()
    with pytest.raises(FileNotFoundError):
        load_settings_from_yaml()


def test_load_settings_from_yaml_yaml_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    broken_yaml = tmp_path / "broken.yaml"
    broken_yaml.write_text("bot_token: [", encoding="utf-8")
    monkeypatch.setattr(settings_module, "_get_config_file_path", lambda: broken_yaml)
    load_settings_from_yaml.cache_clear()
    with pytest.raises(yaml.YAMLError):
        load_settings_from_yaml()


def test_var_config_defaults_are_within_bounds() -> None:
    config = _get_var_config()
    assert 1 <= config.totp_max_attempts <= 10
    assert 1 <= config.bot_polling_timeout <= 300
    assert 1 <= config.bot_long_polling_timeout <= 600


def test_webhook_trusted_proxy_validation() -> None:
    cfg = WebhookConfig(
        url=[SecretStr("https://example.com")],
        webhook_port=[8443],
        local_port=[8080],
        cert=None,
        cert_key=None,
        trusted_proxy_ips=["10.0.0.0/8", "192.168.1.1"],
    )
    assert cfg.trusted_proxy_ips == ["10.0.0.0/8", "192.168.1.1"]

    with pytest.raises(ValidationError):
        WebhookConfig(
            url=[SecretStr("https://example.com")],
            webhook_port=[8443],
            local_port=[8080],
            cert=None,
            cert_key=None,
            trusted_proxy_ips=["invalid-ip"],
        )
