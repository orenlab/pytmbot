from __future__ import annotations

import warnings
from importlib.metadata import PackageNotFoundError
from typing import cast

import pytest
from packaging.version import InvalidVersion
from pydantic import ValidationError

import pytmbot.models.settings_model as settings_model_module
from pytmbot.models.settings_model import (
    ConfigMigrator,
    ConfigVersionError,
    SettingsModel,
    check_config_deprecation,
    get_app_version,
    validate_config_compatibility,
)
from tests._settings_helpers import build_webhook_config

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
    assert get_app_version() == "0.5.1"
    get_app_version.cache_clear()


def test_webhook_config_trusted_proxy_ips_normalization_and_validation() -> None:
    config = build_webhook_config(trusted_proxy_ips=[" 10.0.0.1 ", "192.168.0.0/24"])
    assert config.trusted_proxy_ips == ["10.0.0.1", "192.168.0.0/24"]

    with pytest.raises(ValidationError):
        build_webhook_config(trusted_proxy_ips=[""])


@pytest.mark.parametrize(
    ("config_version", "app_version", "should_raise"),
    [
        (None, "0.2.2", False),
        ("0.2.1", "0.4.0", True),
        ("unknown", "0.4.0", True),
        ("0.3.0.dev0", "0.4.0", True),
        ("0.3.1", "0.4.0", True),
        ("0.3.2", "0.3.2", False),
        ("0.3.2", "0.4.0", True),
        ("0.3.3", "0.3.3", False),
        ("0.3.3", "0.4.0", True),
        ("0.4.0.dev0", "0.4.0.dev0", False),
        ("0.4.0-dev", "0.4.0.dev0", False),
        ("0.4.0.dev0", "0.4.0", True),
        ("0.4.0", "0.4.0", False),
        ("0.5.0.dev0", "0.5.0.dev0", False),
        ("0.5.0-dev", "0.5.0.dev0", False),
        ("0.5.0.dev0", "0.4.0", True),
        ("0.4.0", "0.5.0.dev0", True),
        ("0.5.0.dev0", "0.5.0", True),
        ("0.4.0", "0.5.0", True),
        ("0.5.0", "0.5.0", False),
        ("0.5.0", "0.5.1", True),
        ("0.5.1", "0.5.1", False),
    ],
)
def test_config_migrator_validate_compatibility(
    config_version: str | None,
    app_version: str,
    should_raise: bool,
) -> None:
    if should_raise:
        with pytest.raises((ConfigVersionError, InvalidVersion)):
            validate_config_compatibility(config_version, app_version)
    else:
        validate_config_compatibility(config_version, app_version)


def test_config_migrator_check_deprecation_emits_warning() -> None:
    with pytest.warns(DeprecationWarning):
        check_config_deprecation(None, "0.5.1")

    with pytest.warns(DeprecationWarning):
        check_config_deprecation("0.2.2", "0.5.1")


def test_config_migrator_migrate_config_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_model_module, "get_app_version", lambda: "0.5.1")
    migrator = ConfigMigrator()

    legacy: _ConfigDict = {"bot_token": {"prod_token": ["token"]}}
    migrated_legacy = migrator.migrate_config(_as_object_dict(legacy))
    assert migrated_legacy["config_version"] == "0.5.1"

    outdated: _ConfigDict = {"config_version": "0.2.2"}
    migrated_outdated = migrator.migrate_config(_as_object_dict(outdated))
    assert migrated_outdated["config_version"] == "0.5.1"

    current: _ConfigDict = {"config_version": "0.5.1"}
    assert (
        migrator.migrate_config(_as_object_dict(current))["config_version"] == "0.5.1"
    )


def test_settings_model_migration_and_compatibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(SettingsModel, "app_version", "0.5.1")
    payload = _base_config()

    settings = SettingsModel.model_validate(payload)
    assert settings.config_version == "0.5.1"

    payload_with_mismatch = dict(payload)
    payload_with_mismatch["config_version"] = "0.2.2"
    upgraded = SettingsModel.model_validate(payload_with_mismatch)
    assert upgraded.config_version == "0.5.1"


def test_access_control_requires_admins_subset_of_allowed_users() -> None:
    payload = _base_config()
    payload["access_control"] = {
        "allowed_user_ids": [1],
        "allowed_admins_ids": [2],
        "auth_salt": ["salt-value"],
    }

    with pytest.raises(ValidationError, match="allowed_admins_ids must be a subset"):
        SettingsModel.model_validate(payload)


def test_docker_host_model_optional_connection_fields_have_safe_defaults() -> None:
    model = settings_model_module.DockerHostModel(host=["unix:///var/run/docker.sock"])
    assert model.timeout == 10
    assert model.cert_path is None
    assert model.key_path is None
    assert model.ca_cert is True
    assert model.verify_hostname is True


def test_docker_host_model_accepts_tls_and_timeout_settings() -> None:
    model = settings_model_module.DockerHostModel(
        host=["https://docker.example:2376"],
        timeout=45,
        cert_path="/certs/cert.pem",
        key_path="/certs/key.pem",
        ca_cert="/certs/ca.pem",
        verify_hostname=False,
    )
    assert model.timeout == 45
    assert model.ca_cert == "/certs/ca.pem"
    assert model.verify_hostname is False
    assert (
        settings_model_module.DockerHostModel(host=["x"], ca_cert=False).ca_cert
        is False
    )


@pytest.mark.parametrize(("raw", "expected"), [(1, 5), (10, 10), (900, 300)])
def test_docker_timeout_is_clamped_instead_of_rejected(raw: int, expected: int) -> None:
    from pytmbot.models.settings_model import DockerHostModel

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        model = DockerHostModel(host=["unix:///var/run/docker.sock"], timeout=raw)
    assert model.timeout == expected
