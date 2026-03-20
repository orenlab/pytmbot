from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from typing import cast

import pytest
from packaging.version import InvalidVersion
from pydantic import SecretStr, ValidationError

import pytmbot.models.settings_model as settings_model_module
from pytmbot.models.settings_model import (
    ConfigMigrator,
    ConfigVersionError,
    SettingsModel,
    WebhookConfig,
    get_app_version,
)

type _ConfigScalar = str | int | float | bool | None
type _ConfigValue = _ConfigScalar | dict[str, "_ConfigValue"] | list["_ConfigValue"]
type _ConfigDict = dict[str, _ConfigValue]


def _base_config() -> _ConfigDict:
    return {
        "bot_token": {"prod_token": ["token-value"]},
        "access_control": {
            "allowed_user_ids": [1],
            "allowed_admins_ids": [1],
            "auth_salt": ["salt-value"],
        },
        "docker": {"host": ["unix:///var/run/docker.sock"]},
        "chat_id": {"global_chat_id": [1]},
    }


def _as_object_dict(payload: _ConfigDict) -> dict[str, object]:
    return cast(dict[str, object], payload)


def test_get_app_version_fallback_when_package_not_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_app_version.cache_clear()

    def _raise_not_found(_name: str) -> str:
        raise PackageNotFoundError

    monkeypatch.setattr(settings_model_module, "package_version", _raise_not_found)
    assert get_app_version() == "0.3.0-dev"
    get_app_version.cache_clear()


def test_webhook_config_trusted_proxy_ips_normalization_and_validation() -> None:
    config = WebhookConfig(
        url=[SecretStr("https://example.com")],
        webhook_port=[8443],
        local_port=[8080],
        cert=None,
        cert_key=None,
        trusted_proxy_ips=[" 10.0.0.1 ", "192.168.0.0/24"],
    )
    assert config.trusted_proxy_ips == ["10.0.0.1", "192.168.0.0/24"]

    with pytest.raises(ValidationError):
        WebhookConfig(
            url=[SecretStr("https://example.com")],
            webhook_port=[8443],
            local_port=[8080],
            cert=None,
            cert_key=None,
            trusted_proxy_ips=[""],
        )


@pytest.mark.parametrize(
    ("config_version", "app_version", "should_raise"),
    [
        (None, "0.2.2", False),
        ("0.2.1", "0.3.0-dev", True),
        ("unknown", "0.3.0-dev", True),
        ("0.3.0-dev", "0.3.0", True),
        ("0.3.0-dev", "0.3.0-dev", False),
    ],
)
def test_config_migrator_validate_compatibility(
    config_version: str | None,
    app_version: str,
    should_raise: bool,
) -> None:
    if should_raise:
        with pytest.raises((ConfigVersionError, InvalidVersion)):
            ConfigMigrator.validate_compatibility(config_version, app_version)
    else:
        ConfigMigrator.validate_compatibility(config_version, app_version)


def test_config_migrator_check_deprecation_emits_warning() -> None:
    with pytest.warns(DeprecationWarning):
        ConfigMigrator.check_deprecation(None, "0.3.0-dev")

    with pytest.warns(DeprecationWarning):
        ConfigMigrator.check_deprecation("0.2.2", "0.3.0-dev")


def test_config_migrator_migrate_config_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_model_module, "get_app_version", lambda: "0.3.0-dev")
    migrator = ConfigMigrator()

    legacy: _ConfigDict = {"bot_token": {"prod_token": ["token"]}}
    migrated_legacy = migrator.migrate_config(_as_object_dict(legacy))
    assert migrated_legacy["config_version"] == "0.3.0-dev"

    outdated: _ConfigDict = {"config_version": "0.2.2"}
    migrated_outdated = migrator.migrate_config(_as_object_dict(outdated))
    assert migrated_outdated["config_version"] == "0.3.0-dev"

    current: _ConfigDict = {"config_version": "0.3.0-dev"}
    assert (
        migrator.migrate_config(_as_object_dict(current))["config_version"]
        == "0.3.0-dev"
    )


def test_settings_model_migration_and_compatibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(SettingsModel, "app_version", "0.3.0-dev")
    payload = _base_config()

    settings = SettingsModel.model_validate(payload)
    assert settings.config_version == "0.3.0-dev"

    payload_with_mismatch = dict(payload)
    payload_with_mismatch["config_version"] = "0.2.2"
    upgraded = SettingsModel.model_validate(payload_with_mismatch)
    assert upgraded.config_version == "0.3.0-dev"


def test_access_control_requires_admins_subset_of_allowed_users() -> None:
    payload = _base_config()
    payload["access_control"] = {
        "allowed_user_ids": [1],
        "allowed_admins_ids": [2],
        "auth_salt": ["salt-value"],
    }

    with pytest.raises(ValidationError, match="allowed_admins_ids must be a subset"):
        SettingsModel.model_validate(payload)
