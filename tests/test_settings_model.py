from __future__ import annotations

import re
import warnings
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from typing import cast

import pytest
import yaml
from packaging.version import InvalidVersion
from pydantic import ValidationError

import pytmbot.models.settings_model as settings_model_module
from pytmbot.models.settings_model import (
    ConfigMigrator,
    ConfigVersionError,
    DockerHostModel,
    SettingsModel,
    check_config_deprecation,
    get_app_version,
    validate_config_compatibility,
)
from tests._settings_helpers import build_webhook_config

SAMPLE_CONFIG_PATH = Path(__file__).resolve().parents[1] / "pytmbot.yaml.sample"
DOCKER_HOST = ["unix:///var/run/docker.sock"]

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
    assert get_app_version() == "0.5.4"
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
        ("0.5.1", "0.5.2", True),
        ("0.5.2", "0.5.2", False),
        ("0.5.2", "0.5.3", True),
        ("0.5.3", "0.5.3", False),
        ("0.5.3", "0.5.4", True),
        ("0.5.4", "0.5.4", False),
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
        check_config_deprecation(None, "0.5.4")

    with pytest.warns(DeprecationWarning):
        check_config_deprecation("0.2.2", "0.5.4")


def test_config_migrator_migrate_config_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings_model_module, "get_app_version", lambda: "0.5.4")
    migrator = ConfigMigrator()

    legacy: _ConfigDict = {"bot_token": {"prod_token": ["token"]}}
    migrated_legacy = migrator.migrate_config(_as_object_dict(legacy))
    assert migrated_legacy["config_version"] == "0.5.4"

    outdated: _ConfigDict = {"config_version": "0.2.2"}
    migrated_outdated = migrator.migrate_config(_as_object_dict(outdated))
    assert migrated_outdated["config_version"] == "0.5.4"

    current: _ConfigDict = {"config_version": "0.5.4"}
    assert (
        migrator.migrate_config(_as_object_dict(current))["config_version"] == "0.5.4"
    )


def test_settings_model_migration_and_compatibility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(SettingsModel, "app_version", "0.5.4")
    payload = _base_config()

    settings = SettingsModel.model_validate(payload)
    assert settings.config_version == "0.5.4"

    payload_with_mismatch = dict(payload)
    payload_with_mismatch["config_version"] = "0.2.2"
    upgraded = SettingsModel.model_validate(payload_with_mismatch)
    assert upgraded.config_version == "0.5.4"


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


@pytest.mark.parametrize("value", ["0.0.0.0/0", "::/0", "10.1.2.3/0"])
def test_trusted_proxy_ips_reject_networks_that_trust_everyone(value: str) -> None:
    expected = f"trusted_proxy_ips value '{value}' trusts every address"
    with pytest.raises(ValidationError, match=re.escape(expected)):
        build_webhook_config(trusted_proxy_ips=["10.0.0.0/8", value])

    # Wide but bounded proxy networks stay the operator's choice.
    assert build_webhook_config(trusted_proxy_ips=["10.0.0.0/8", "fd00::/8"])


def test_additional_telegram_ranges_accept_ranges_up_to_the_limit() -> None:
    config = build_webhook_config(
        additional_telegram_ip_ranges=[" 149.154.0.0/16 ", "2001:b28::/32", "1.2.3.4"]
    )
    assert config.additional_telegram_ip_ranges == [
        "149.154.0.0/16",
        "2001:b28::/32",
        "1.2.3.4",
    ]

    with pytest.raises(
        ValidationError,
        match=re.escape("Invalid additional_telegram_ip_ranges IP/CIDR value: 'x'"),
    ):
        build_webhook_config(additional_telegram_ip_ranges=["x"])
    with pytest.raises(
        ValidationError,
        match="additional_telegram_ip_ranges cannot contain empty values",
    ):
        build_webhook_config(additional_telegram_ip_ranges=[" "])


@pytest.mark.parametrize(
    ("value", "limit"),
    [
        ("0.0.0.0/0", "IPv4 ranges must be /16 or narrower"),
        ("149.154.0.0/15", "IPv4 ranges must be /16 or narrower"),
        ("::/0", "IPv6 ranges must be /32 or narrower"),
        ("2001:b28::/31", "IPv6 ranges must be /32 or narrower"),
    ],
)
def test_additional_telegram_ranges_reject_wide_networks(
    value: str, limit: str
) -> None:
    expected = f"additional_telegram_ip_ranges value '{value}' is too wide: {limit}"
    with pytest.raises(ValidationError, match=re.escape(expected)):
        build_webhook_config(additional_telegram_ip_ranges=["91.108.56.0/22", value])


def test_docker_stop_and_restart_timeouts_default_and_accept_values() -> None:
    default = DockerHostModel(host=DOCKER_HOST)
    assert (default.stop_timeout, default.restart_timeout) == (10, 10)

    with warnings.catch_warnings():
        warnings.simplefilter("error")  # in-range values never warn
        model = DockerHostModel(host=DOCKER_HOST, stop_timeout=1, restart_timeout=300)
    assert (model.stop_timeout, model.restart_timeout) == (1, 300)

    with pytest.raises(ValidationError):
        DockerHostModel.model_validate({"host": DOCKER_HOST, "stop_timeout": "soon"})


@pytest.mark.parametrize(
    ("field_name", "raw", "expected"),
    [
        ("stop_timeout", 0, 1),
        ("stop_timeout", -5, 1),
        ("restart_timeout", 301, 300),
        ("restart_timeout", 3600, 300),
    ],
)
def test_docker_stop_and_restart_timeouts_are_clamped_like_timeout(
    field_name: str, raw: int, expected: int
) -> None:
    message = f"docker.{field_name}={raw} is outside 1-300 seconds; using {expected}"
    with pytest.warns(UserWarning, match=re.escape(message)):
        model = DockerHostModel.model_validate({"host": DOCKER_HOST, field_name: raw})
    assert model.model_dump()[field_name] == expected


def test_sample_config_documents_real_docker_timeout_fields() -> None:
    # Pydantic drops unknown keys silently: every documented key must exist.
    sample_text = SAMPLE_CONFIG_PATH.read_text(encoding="utf-8")
    for commented in ("# timeout: 10", "# stop_timeout: 10", "# restart_timeout: 10"):
        assert commented in sample_text
        sample_text = sample_text.replace(commented, commented.removeprefix("# "))

    docker = SettingsModel.model_validate(yaml.safe_load(sample_text)).docker
    assert docker.model_fields_set >= {"timeout", "stop_timeout", "restart_timeout"}


def test_ipv4_mapped_catch_all_trusted_proxy_is_rejected() -> None:
    # ::ffff:0.0.0.0/96 is 0.0.0.0/0 once unmapped.
    with pytest.raises(ValidationError):
        build_webhook_config(trusted_proxy_ips=["::ffff:0.0.0.0/96"])
