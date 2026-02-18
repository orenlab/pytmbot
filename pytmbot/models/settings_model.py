#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.

Enhanced with configuration versioning and validation.
"""

import warnings
from functools import cache
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as package_version
from ipaddress import ip_network
from typing import Any, ClassVar

from packaging import version
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings

from pytmbot import logs


@cache
def get_app_version() -> str:
    """
    Resolve application version without importing `pytmbot.globals`.

    Importing `globals` from this module creates a circular dependency during
    startup (`settings_model -> globals -> keyboards -> exceptions -> utils.security -> settings_model`).
    """
    try:
        return package_version("pyTMBot")
    except PackageNotFoundError:
        # Source/development fallback when package metadata is unavailable.
        return "0.3.0-dev"


class ConfigVersionError(Exception):
    """Custom exception for configuration version errors."""

    pass


class BotTokenModel(BaseModel):
    """
    Model to store bot token information for production and development environments.

    Attributes:
        prod_token (List[SecretStr]): List of production bot tokens.
        dev_bot_token (Optional[List[SecretStr]]): Optional list of development bot tokens.
    """

    prod_token: list[SecretStr] = Field(min_length=1)
    dev_bot_token: list[SecretStr] | None = Field(default=None, min_length=1)


class AccessControlModel(BaseModel):
    """
    Model to handle access control settings such as allowed users and admins, and authorization salt.

    Attributes:
        allowed_user_ids (List[int]): List of user IDs that are allowed access.
        allowed_admins_ids (List[int]): List of admin IDs that have elevated permissions.
        auth_salt (List[SecretStr]): List of secret salts for authorization.
    """

    allowed_user_ids: list[int] = Field(min_length=1)
    allowed_admins_ids: list[int] = Field(min_length=1)
    auth_salt: list[SecretStr] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_admins_subset(self) -> "AccessControlModel":
        """Ensure admins are always part of allowed users."""
        allowed_users = set(self.allowed_user_ids)
        invalid_admins = [
            admin_id for admin_id in self.allowed_admins_ids if admin_id not in allowed_users
        ]
        if invalid_admins:
            raise ValueError(
                "allowed_admins_ids must be a subset of allowed_user_ids. "
                f"Unknown admin IDs: {invalid_admins}"
            )
        return self


class DockerHostModel(BaseModel):
    """
    Model to store Docker host information.

    Attributes:
        host (List[str]): List of Docker host URLs or IP addresses.
        debug_docker_client (bool): Enable debug logging for Docker client.
    """

    host: list[str] = Field(min_length=1)
    debug_docker_client: bool = False


class InfluxDBModel(BaseModel):
    """
    Model to store InfluxDB information.

    Attributes:
        url (List[str]): List of InfluxDB URLs.
        token (List[SecretStr]): List of InfluxDB tokens.
        org (List[str]): List of InfluxDB organizations.
        bucket (List[str]): List of InfluxDB buckets.
        debug_mode (bool): Enable debug mode for InfluxDB.
    """

    url: list[SecretStr] | None = Field(default=None, min_length=1)
    token: list[SecretStr] | None = Field(default=None, min_length=1)
    org: list[SecretStr] | None = Field(default=None, min_length=1)
    bucket: list[SecretStr] | None = Field(default=None, min_length=1)
    debug_mode: bool = False


class ChatIdModel(BaseModel):
    """
    Model to handle optional chat ID configurations for global notifications.

    Attributes:
        global_chat_id (Optional[List[int]]): Optional list of chat IDs for global notifications.
    """

    global_chat_id: list[int] = Field(min_length=1)


class TraceholdSettings(BaseModel):
    """
    Model to define threshold settings for CPU, memory, and disk usage monitoring.
    """

    cpu_usage_threshold: list[int] = Field(min_length=1, max_length=1)
    memory_usage_threshold: list[int] = Field(min_length=1, max_length=1)
    disk_usage_threshold: list[int] = Field(min_length=1, max_length=1)
    cpu_temperature_threshold: list[int] = Field(min_length=1, max_length=1)
    gpu_temperature_threshold: list[int] = Field(min_length=1, max_length=1)
    disk_temperature_threshold: list[int] = Field(min_length=1, max_length=1)


class MonitorConfig(BaseModel):
    """
    Model to configure monitoring settings for the bot.
    """

    tracehold: TraceholdSettings
    max_notifications: list[int] = Field(min_length=1, max_length=1)
    check_interval: list[int] = Field(min_length=1, max_length=1)
    reset_notification_count: list[int] = Field(min_length=1, max_length=1)
    retry_attempts: list[int] = Field(min_length=1, max_length=2)
    retry_interval: list[int] = Field(min_length=1, max_length=2)
    monitor_docker: bool = False


class OutlineVPN(BaseModel):
    """
    Model to store Outline VPN settings.
    """

    api_url: list[SecretStr] = Field(min_length=1)
    cert: list[SecretStr] = Field(min_length=1)


class PluginsConfig(BaseModel):
    """
    Model to configure additional plugins for the bot, such as monitoring and Outline VPN.
    """

    monitor: MonitorConfig | None = None
    outline: OutlineVPN | None = None


class WebhookConfig(BaseModel):
    """
    Model to configure webhook settings for the bot.
    """

    url: list[SecretStr] = Field(min_length=1)
    webhook_port: list[int] = Field(min_length=1)
    local_port: list[int] = Field(min_length=1)
    cert: list[SecretStr] | None = Field(default=None, min_length=1)
    cert_key: list[SecretStr] | None = Field(default=None, min_length=1)
    trusted_proxy_ips: list[str] | None = Field(default=None, min_length=1)

    @field_validator("trusted_proxy_ips")
    @classmethod
    def validate_trusted_proxy_ips(
        cls, value: list[str] | None
    ) -> list[str] | None:
        """Validate trusted proxy IPs/CIDRs format."""
        if value is None:
            return None

        normalized: list[str] = []
        for raw_ip in value:
            candidate = raw_ip.strip()
            if not candidate:
                raise ValueError("trusted_proxy_ips cannot contain empty values")

            try:
                _ = ip_network(candidate, strict=False)
            except ValueError as error:
                raise ValueError(
                    f"Invalid trusted proxy IP/CIDR value: '{candidate}'"
                ) from error
            normalized.append(candidate)

        return normalized


class ConfigMigrator(logs.BaseComponent):
    """
    Handles configuration migrations between versions.
    """

    def __init__(self) -> None:
        super().__init__("config_migrator")
        self.app_version = get_app_version()

    @staticmethod
    def get_supported_versions() -> list[str]:
        """Get list of supported configuration versions."""
        return ["0.2.2", "0.3.0-dev", "0.3.0"]

    @staticmethod
    def get_compatibility_matrix() -> dict[str, dict[str, str]]:
        """
        Returns compatibility matrix for config versions with app versions.
        Config version should match app version exactly.

        Returns:
            Dict mapping config versions to compatibility info.
        """
        return {
            "0.2.2": {
                "min_app": "0.2.2",
                "max_app": "0.2.2",
                "description": "Legacy version (minimum supported)",
            },
            "0.3.0-dev": {
                "min_app": "0.3.0-dev",
                "max_app": "0.3.0-dev",
                "description": "Development version with config versioning",
            },
            "0.3.0": {
                "min_app": "0.3.0",
                "max_app": "0.3.0",
                "description": "Stable release with config versioning",
            },
        }

    @classmethod
    def validate_compatibility(
        cls, config_version: str | None, app_version: str
    ) -> None:
        """
        Validate compatibility between config and app versions.
        Config version should match app version exactly.

        Args:
            config_version: Version of the configuration (None for legacy configs)
            app_version: Version of the application

        Raises:
            ConfigVersionError: If versions are incompatible
        """
        # Handle special case: no config version means legacy (0.2.2 compatibility)
        if config_version is None:
            app_ver_clean = app_version.replace("-dev", "")
            if version.parse(app_ver_clean) < version.parse("0.2.2"):
                raise ConfigVersionError(
                    f"App version '{app_version}' is End-of-Life (< 0.2.2). "
                    f"Minimum supported version is 0.2.2"
                )
            return  # Legacy configs are allowed for 0.2.2+

        # Check for EOL versions FIRST, before checking compatibility matrix
        config_ver_clean = config_version.replace("-dev", "")
        if version.parse(config_ver_clean) < version.parse("0.2.2"):
            raise ConfigVersionError(
                f"Configuration version '{config_version}' is End-of-Life (< 0.2.2). "
                f"Minimum supported version is 0.2.2. "
                f"Current app version: {app_version}"
            )

        matrix = cls.get_compatibility_matrix()

        if config_version not in matrix:
            supported = list(matrix.keys())
            raise ConfigVersionError(
                f"Unsupported config version '{config_version}'. "
                f"Supported versions: {supported}"
            )

        # Config version should match app version exactly
        if config_version != app_version:
            raise ConfigVersionError(
                f"Config version '{config_version}' does not match "
                f"app version '{app_version}'. They should be identical."
            )

    @classmethod
    def check_deprecation(cls, config_version: str | None, app_version: str) -> None:
        """
        Check if config version is deprecated and issue warnings.

        Args:
            config_version: Version to check (None for legacy configs)
            app_version: Current app version
        """
        # Check for legacy configs without version
        if config_version is None:
            warnings.warn(
                f"Configuration without version field detected. "
                f"This is legacy 0.2.2 compatibility mode. "
                f"Consider adding 'config_version: \"{app_version}\"' to your config.",
                DeprecationWarning,
                stacklevel=3,
            )
            return

        # Version 0.2.2 is considered legacy
        if config_version == "0.2.2":
            warnings.warn(
                f"Configuration version '{config_version}' is legacy. "
                f"Consider upgrading to version {app_version} for new features.",
                DeprecationWarning,
                stacklevel=3,
            )

    def migrate_config(self, config_data: dict[str, Any]) -> dict[str, Any]:
        """
        Migrate configuration to current app version.

        Args:
            config_data: Raw configuration data

        Returns:
            Migrated configuration data
        """
        current_version = config_data.get("config_version")

        # If no version, this is legacy 0.2.2 config - add current app version
        if current_version is None:
            with self.log_context(
                legacy_config=True, app_version=self.app_version
            ) as log:
                log.info("bot.models.settings_model.adding.config.info")
            config_data["config_version"] = self.app_version
            return config_data

        # If version doesn't match current app version, update it
        if current_version != self.app_version:
            with self.log_context(
                old_version=current_version, new_version=self.app_version
            ) as log:
                log.info("bot.models.settings_model.updating.config.info")
            config_data["config_version"] = self.app_version

        return config_data


class SettingsModel(BaseSettings):
    """
    Main settings model for configuring the bot with version management.

    Attributes:
        config_version (Optional[str]): Version of the configuration schema.
        bot_token (BotTokenModel): Bot token settings for both production and development.
        access_control (AccessControlModel): Access control settings for users and admins.
        docker (DockerHostModel): Docker host settings.
        chat_id (ChatIdModel): Chat ID settings for global notifications.
        influxdb (Optional[InfluxDBModel]): Optional InfluxDB configuration.
        plugins_config (Optional[PluginsConfig]): Optional plugin configurations.
        webhook_config (Optional[WebhookConfig]): Optional webhook configuration.
    """

    # Configuration version - should match app version
    # Default to None for backward compatibility with 0.2.2 configs
    app_version: ClassVar[str] = get_app_version()
    config_version: str | None = None

    # Core configuration
    bot_token: BotTokenModel
    access_control: AccessControlModel
    docker: DockerHostModel
    chat_id: ChatIdModel

    # Optional configurations
    influxdb: InfluxDBModel | None = None
    plugins_config: PluginsConfig | None = None
    webhook_config: WebhookConfig | None = None

    @classmethod
    @field_validator("config_version")
    def validate_config_version(cls, v: str | None) -> str | None:
        """
        Validate configuration version against application compatibility.

        Args:
            v: Configuration version string (can be None for legacy configs)

        Returns:
            Validated version string

        Raises:
            ConfigVersionError: If version is incompatible
        """
        try:
            # Check for EOL versions and validate compatibility
            ConfigMigrator.validate_compatibility(v, cls.app_version)

            # Check for deprecation warnings
            ConfigMigrator.check_deprecation(v, cls.app_version)

            return v

        except ConfigVersionError as e:
            # Re-raise ConfigVersionError as ValueError for Pydantic
            raise ValueError(f"Configuration version validation failed: {str(e)}")
        except Exception as e:
            raise ValueError(f"Configuration version validation failed: {str(e)}")

    @classmethod
    @model_validator(mode="before")
    def migrate_config_if_needed(cls, values: dict[str, Any]) -> dict[str, Any]:
        """
        Automatically add or update config_version field.
        Handle configs without version field (0.2.2 compatibility).

        Args:
            values: Raw configuration values

        Returns:
            Updated configuration values
        """
        config_version = values.get("config_version")

        # Create migrator instance for logging
        migrator = ConfigMigrator()

        # Handle legacy configs or version mismatches
        match config_version:
            case None:
                with migrator.log_context(
                    legacy_config=True, app_version=cls.app_version
                ) as log:
                    log.debug(
                        "bot.models.settings_model.no.config.debug"
                    )
                values["config_version"] = cls.app_version
            case version if version != cls.app_version:
                with migrator.log_context(
                    old_version=config_version,
                    new_version=cls.app_version,
                    migration_required=True,
                ) as log:
                    log.info("bot.models.settings_model.config.version.info")
                values = migrator.migrate_config(values)

        return values

    def get_version_info(self) -> dict[str, Any]:
        """
        Get detailed version information.

        Returns:
            Dictionary with version details
        """
        matrix = ConfigMigrator.get_compatibility_matrix()
        config_info = matrix.get(self.config_version or "legacy", {})

        return {
            "config_version": self.config_version or "legacy (None)",
            "app_version": self.app_version,
            "description": config_info.get("description", "Legacy 0.2.2 compatibility"),
            "is_deprecated": self.config_version
            in [None, "0.2.2"],  # Legacy compatibility
            "is_legacy": self.config_version is None,
            "versions_match": self.config_version == self.app_version,
        }

    def validate_full_compatibility(self) -> bool:
        """
        Perform full compatibility validation.

        Returns:
            True if configuration is fully compatible

        Raises:
            ConfigVersionError: If configuration is incompatible
        """
        try:
            ConfigMigrator.validate_compatibility(self.config_version, self.app_version)
            return True
        except ConfigVersionError:
            raise


# Utility functions for configuration management
def load_config_with_migration(config_path: str) -> SettingsModel:
    """
    Load configuration with automatic migration support.

    Args:
        config_path: Path to configuration file

    Returns:
        Loaded and validated settings
    """
    import yaml  # type: ignore[import-untyped]

    # Create logger for config loading
    class ConfigLoader(logs.BaseComponent):
        def __init__(self) -> None:
            super().__init__("config_loader")

    loader = ConfigLoader()

    try:
        with open(config_path, encoding="utf-8") as f:
            config_data = yaml.safe_load(f)

        # Create settings (migration happens automatically in model_validator)
        settings = SettingsModel(**config_data)

        version_info = settings.get_version_info()
        with loader.log_context(config_path=config_path, **version_info) as log:
            log.info("bot.models.settings_model.config.load.ok")

        return settings

    except Exception as e:
        with loader.log_context(
            config_path=config_path, error=str(e), error_type=type(e).__name__
        ) as log:
            log.error("bot.models.settings_model.load.config.fail")
        raise
