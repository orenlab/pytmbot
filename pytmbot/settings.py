#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import os
from functools import lru_cache

import yaml
from pydantic import BaseModel

from pytmbot.models.settings_model import SettingsModel


def get_config_file_path() -> str:
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
        with open(get_config_file_path(), "r") as f:
            settings_data = yaml.safe_load(f)
        return SettingsModel(**settings_data)
    except FileNotFoundError:
        raise FileNotFoundError("pytmbot.yaml not found")


class KeyboardSettings(BaseModel):
    """
    Configuration settings for bot keyboards.

    Attributes:
        main_keyboard (frozenset[dict[str, str]]): The main keyboard settings.
        docker_keyboard (frozenset[dict[str, str]]): The Docker keyboard settings.
        auth_keyboard (frozenset[dict[str, str]]): The authentication keyboard settings.
        auth_processing_keyboard (frozenset[dict[str, str]]): The keyboard used during authentication processing.
        back_keyboard (frozenset[dict[str, str]]): The back navigation keyboard settings.
    """

    main_keyboard: frozenset[dict[str, str]] = {
        "rocket": "Server",
        "spouting_whale": "Docker",
        "lollipop": "Plugins",
        "mushroom": "About me",
    }
    server_keyboard: frozenset[dict[str, str]] = {
        "low_battery": "Load average",
        "pager": "Memory load",
        "stopwatch": "Sensors",
        "rocket": "Process",
        "flying_saucer": "Uptime",
        "floppy_disk": "File system",
        "satellite": "Network",
    }
    docker_keyboard: frozenset[dict[str, str]] = {
        "framed_picture": "Images",
        "toolbox": "Containers",
    }
    auth_keyboard: frozenset[dict[str, str]] = {
        "first_quarter_moon": "Get QR-code for 2FA app",
        "fountain_pen": "Enter 2FA code",
    }
    auth_processing_keyboard: frozenset[dict[str, str]] = {
        "fountain_pen": "Enter 2FA code",
    }
    back_keyboard: frozenset[dict[str, str]] = {"BACK_arrow": "Back to main menu"}


class BotCommandSettings(BaseModel):
    """
    Configuration settings for bot commands.

    Attributes:
        bot_commands (frozenset[dict[str, str]]): The bot commands with descriptions.
    """

    bot_commands: frozenset[dict[str, str]] = {
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
        bot_description (frozenset[str]): The description of the bot.
    """

    bot_description: frozenset[str] = (
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
    """

    template_path: str = os.path.join(os.path.dirname(__file__), "templates")
    totp_max_attempts: int = 3
    bot_polling_timeout: int = 30
    bot_long_polling_timeout: int = 60


class LogsSettings(BaseModel):
    """
    Configuration settings for logging.

    Attributes:
        valid_log_levels (frozenset[str]): Set of valid log levels.
        bot_logger_format (str): Format of the bot logger output.
    """

    valid_log_levels: frozenset[str] = frozenset(["ERROR", "INFO", "DEBUG"])
    bot_logger_format: str = (
        "<green>{time:YYYY-MM-DD}</green> "
        "[<cyan>{time:HH:mm:ss}</cyan>]"
        "[<level>{level: <8}</level>]"
        "[<magenta>{module: <16}</magenta>] › "
        "<level>{message}</level> "
    )


# Load settings and configurations
settings = load_settings_from_yaml()
var_config = VarConfig()
log_settings = LogsSettings()
keyboard_settings = KeyboardSettings()
bot_command_settings = BotCommandSettings()
bot_description_settings = BotDescriptionSettings()
