#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import os
import re
from functools import cache
from pathlib import Path
from typing import Final

import yaml
from pydantic import BaseModel, ConfigDict, Field

from pytmbot.models.settings_model import SettingsModel

# Constants
MAX_CONTAINER_NAME_LENGTH: Final[int] = 253
CONTAINER_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*$"
)
CONFIG_PATH_ENV_VAR: Final[str] = "PYTMBOT_CONFIG_PATH"


def _get_config_file_path() -> Path:
    """
    Constructs the path to the settings YAML file.

    Returns:
        Path: The path to the settings YAML file.
    """
    env_config_path = os.getenv(CONFIG_PATH_ENV_VAR)
    if env_config_path:
        return Path(env_config_path).expanduser().resolve()
    return Path(__file__).parent.parent / "pytmbot.yaml"


@cache
def load_settings_from_yaml() -> SettingsModel:
    """
    Loads settings from a YAML file and returns an instance of SettingsModel.

    Returns:
        SettingsModel: The settings model with data from the YAML file.

    Raises:
        FileNotFoundError: If the YAML file is not found.
        yaml.YAMLError: If there is an error parsing the YAML file.
    """
    config_path = _get_config_file_path()
    try:
        with config_path.open("r", encoding="utf-8") as f:
            settings_data = yaml.safe_load(f)
        return SettingsModel(**settings_data)
    except FileNotFoundError as error:
        raise FileNotFoundError(
            f"Configuration file not found: {config_path}"
        ) from error
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"Error parsing YAML file: {e}") from e


def get_default_main_keyboard() -> dict[str, str]:
    """Returns the default main keyboard configuration."""
    return {
        "rocket": "Server",
        "spouting_whale": "Docker",
        "lollipop": "Plugins",
        "eyes": "Quick view",
        "stethoscope": "Health",
        "mushroom": "About me",
    }


def get_default_server_keyboard() -> dict[str, str]:
    """Returns the default server keyboard configuration."""
    return {
        "low_battery": "Load average",
        "electric_plug": "CPU",
        "pager": "Memory load",
        "stopwatch": "Sensors",
        "rocket": "Process",
        "flying_saucer": "Uptime",
        "floppy_disk": "File system",
        "satellite": "Network",
    }


def get_default_docker_keyboard() -> dict[str, str]:
    """Returns the default docker keyboard configuration."""
    return {
        "framed_picture": "Images",
        "toolbox": "Containers",
    }


def get_default_auth_keyboard() -> dict[str, str]:
    """Returns the default auth keyboard configuration."""
    return {
        "first_quarter_moon": "Get QR-code for 2FA app",
        "fountain_pen": "Enter 2FA code",
    }


def get_default_auth_processing_keyboard() -> dict[str, str]:
    """Returns the default auth processing keyboard configuration."""
    return {
        "fountain_pen": "Enter 2FA code",
    }


def get_default_back_keyboard() -> dict[str, str]:
    """Returns the default back keyboard configuration."""
    return {"BACK_arrow": "Back to main menu"}


def get_default_bot_commands() -> dict[str, str]:
    """Returns the default bot commands configuration."""
    return {
        "/start": "Start bot!",
        "/help": "Get help",
        "/docker": "Launch the section about Docker",
        "/containers": "Get Containers info",
        "/images": "Get Images info",
        "/health": "Get current system health snapshot",
        "/qrcode": "Get TOTP QR code for 2FA app",
        "/back": "Back to main menu",
        "/check_bot_updates": "Check for software updates",
        "getmyid": "Check user and current chat credential",
    }


class KeyboardSettings(BaseModel):
    """
    Configuration settings for bot keyboards.

    Attributes:
        main_keyboard: The main keyboard settings.
        server_keyboard: The server keyboard settings.
        docker_keyboard: The Docker keyboard settings.
        auth_keyboard: The authentication keyboard settings.
        auth_processing_keyboard: The keyboard used during authentication.
        back_keyboard: The back navigation keyboard settings.
    """

    model_config = ConfigDict(frozen=True)

    main_keyboard: dict[str, str] = Field(default_factory=get_default_main_keyboard)
    server_keyboard: dict[str, str] = Field(default_factory=get_default_server_keyboard)
    docker_keyboard: dict[str, str] = Field(default_factory=get_default_docker_keyboard)
    auth_keyboard: dict[str, str] = Field(default_factory=get_default_auth_keyboard)
    auth_processing_keyboard: dict[str, str] = Field(
        default_factory=get_default_auth_processing_keyboard
    )
    back_keyboard: dict[str, str] = Field(default_factory=get_default_back_keyboard)


class BotCommandSettings(BaseModel):
    """
    Configuration settings for bot commands.

    Attributes:
        bot_commands: The bot commands with descriptions.
    """

    model_config = ConfigDict(frozen=True)

    bot_commands: dict[str, str] = Field(default_factory=get_default_bot_commands)


class BotDescriptionSettings(BaseModel):
    """
    Configuration settings for the bot description.

    Attributes:
        bot_description: The description of the bot.
    """

    model_config = ConfigDict(frozen=True)

    bot_description: str = Field(
        default="pyTMBot - A simple Telegram bot designed to gather basic information "
        "about the status of your local servers"
    )


class VarConfig(BaseModel):
    """
    Configuration settings for various variables used by the bot.

    Attributes:
        template_path: Path to the template directory.
        totp_max_attempts: Maximum attempts for TOTP authentication.
        bot_polling_timeout: Timeout for bot polling.
        bot_long_polling_timeout: Timeout for long polling.
    """

    model_config = ConfigDict(frozen=True)

    template_path: str = Field(
        default_factory=lambda: str(Path(__file__).parent / "templates")
    )
    totp_max_attempts: int = Field(default=3, ge=1, le=10)
    bot_polling_timeout: int = Field(default=30, ge=1, le=300)
    bot_long_polling_timeout: int = Field(default=60, ge=1, le=600)


@cache
def _get_settings() -> SettingsModel:
    """Cached settings loader."""
    return load_settings_from_yaml()


@cache
def _get_var_config() -> VarConfig:
    """Cached var config loader."""
    return VarConfig()


@cache
def _get_keyboard_settings() -> KeyboardSettings:
    """Cached keyboard settings loader."""
    return KeyboardSettings()


@cache
def _get_bot_command_settings() -> BotCommandSettings:
    """Cached bot command settings loader."""
    return BotCommandSettings()


@cache
def _get_bot_description_settings() -> BotDescriptionSettings:
    """Cached bot description settings loader."""
    return BotDescriptionSettings()


def __getattr__(name: str) -> object:
    """Lazy-loaded module attributes for backward compatibility."""
    match name:
        case "settings":
            return _get_settings()
        case "var_config":
            return _get_var_config()
        case "keyboard_settings":
            return _get_keyboard_settings()
        case "bot_command_settings":
            return _get_bot_command_settings()
        case "bot_description_settings":
            return _get_bot_description_settings()
        case _:
            raise AttributeError(f"module '{__name__}' has no attribute '{name}'")
