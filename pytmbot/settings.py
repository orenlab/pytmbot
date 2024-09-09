#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import FrozenSet

import yaml
from pydantic import BaseModel

from pytmbot.models.settings_model import SettingsModel


def get_env_file_path() -> str:
    """
    Constructs the path to the settings YAML file.

    Returns:
        str: The path to the settings YAML file.
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(current_dir)
    env_file_path = os.path.join(root_dir, "pytmbot.yaml")

    return env_file_path


@lru_cache(maxsize=None)
def load_settings_from_yaml() -> SettingsModel:
    """
    Loads settings from a YAML file and returns an instance of SettingsModel.

    Returns:
        SettingsModel: The settings model with data from the YAML file.

    Raises:
        FileNotFoundError: If the YAML file is not found.
        yaml.YAMLError: If there is an error parsing the YAML file.
    """
    try:
        with open(get_env_file_path(), "r") as f:
            settings_data = yaml.safe_load(f)
        return SettingsModel(**settings_data)
    except FileNotFoundError:
        raise FileNotFoundError("pytmbot.yaml not found")


class KeyboardSettings(BaseModel):
    """
    Configuration settings for bot keyboards.

    Attributes:
        main_keyboard (FrozenSet[dict[str, str]]): The main keyboard settings.
        docker_keyboard (FrozenSet[dict[str, str]]): The Docker keyboard settings.
        auth_keyboard (FrozenSet[dict[str, str]]): The authentication keyboard settings.
        auth_processing_keyboard (FrozenSet[dict[str, str]]): The keyboard used during authentication processing.
        back_keyboard (FrozenSet[dict[str, str]]): The back navigation keyboard settings.
    """

    main_keyboard: FrozenSet[dict[str, str]] = {
        "low_battery": "Load average",
        "pager": "Memory load",
        "stopwatch": "Sensors",
        "rocket": "Process",
        "flying_saucer": "Uptime",
        "floppy_disk": "File system",
        "spouting_whale": "Docker",
        "satellite": "Network",
        "turtle": "About me",
    }
    docker_keyboard: FrozenSet[dict[str, str]] = {
        "framed_picture": "Images",
        "toolbox": "Containers",
        "BACK_arrow": "Back to main menu",
    }
    auth_keyboard: FrozenSet[dict[str, str]] = {
        "first_quarter_moon": "Get QR-code for 2FA app",
        "fountain_pen": "Enter 2FA code",
        "BACK_arrow": "Back to main menu",
    }
    auth_processing_keyboard: FrozenSet[dict[str, str]] = {
        "fountain_pen": "Enter 2FA code",
        "BACK_arrow": "Back to main menu",
    }
    back_keyboard: FrozenSet[dict[str, str]] = {"BACK_arrow": "Back to main menu"}


class BotCommandSettings(BaseModel):
    """
    Configuration settings for bot commands.

    Attributes:
        bot_commands (FrozenSet[dict[str, str]]): The bot commands with descriptions.
    """

    bot_commands: FrozenSet[dict[str, str]] = {
        "/start": "Start bot!",
        "/help": "Get help",
        "/docker": "Launch the section about Docker",
        "/containers": "Get Containers info",
        "/images": "Get Images info",
        "/qrcode": "Get TOTP QR code for 2FA app",
        "/back": "Back to main menu",
        "/check_bot_updates": "Check for software updates",
    }


class BotDescriptionSettings(BaseModel):
    """
    Configuration settings for the bot description.

    Attributes:
        bot_description (FrozenSet[str]): The description of the bot.
    """

    bot_description: FrozenSet[str] = (
        "pyTMBot - A simple Telegram bot designed to gather basic information about the status of your local servers"
    )


class VarConfig(BaseModel):
    """
    Configuration settings for various variables used by the bot.

    Attributes:
        template_path (str): Path to the template directory.
        totp_max_attempts (int): Maximum attempts for TOTP authentication.
        bot_polling_timeout (int): Timeout for bot polling.
        bot_long_polling_timeout (int): Timeout for long polling.
        plugin_template_path (str): Path to the plugin template directory.
    """

    template_path: str = os.path.join(os.path.dirname(__file__), "templates")
    totp_max_attempts: int = 3
    bot_polling_timeout: int = 30
    bot_long_polling_timeout: int = 60
    plugin_template_path: str = os.path.join(os.path.dirname(__file__), "plugins")


class LogsSettings(BaseModel):
    """
    Configuration settings for logging.

    Attributes:
        valid_log_levels (FrozenSet[str]): Set of valid log levels.
        bot_logger_format (str): Format of the bot logger output.
    """

    valid_log_levels: FrozenSet[str] = frozenset(["ERROR", "INFO", "DEBUG"])
    bot_logger_format: str = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | <level>{message}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan>"
    )


# Load settings and configurations
settings = load_settings_from_yaml()
var_config = VarConfig()
log_settings = LogsSettings()
keyboard_settings = KeyboardSettings()
bot_command_settings = BotCommandSettings()
bot_description_settings = BotDescriptionSettings()
