#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import Dict, FrozenSet, ClassVar

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
    return os.path.join(root_dir, "pytmbot.yaml")


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
    config_path = get_config_file_path()
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            settings_data = yaml.safe_load(f)
        return SettingsModel(**settings_data)
    except FileNotFoundError:
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"Error parsing YAML file: {e}")


def get_default_main_keyboard() -> Dict[str, str]:
    return {
        "rocket": "Server",
        "spouting_whale": "Docker",
        "lollipop": "Plugins",
        "mushroom": "About me",
    }


def get_default_server_keyboard() -> Dict[str, str]:
    return {
        "low_battery": "Load average",
        "pager": "Memory load",
        "stopwatch": "Sensors",
        "rocket": "Process",
        "flying_saucer": "Uptime",
        "floppy_disk": "File system",
        "satellite": "Network",
    }


def get_default_docker_keyboard() -> Dict[str, str]:
    return {
        "framed_picture": "Images",
        "toolbox": "Containers",
    }


def get_default_auth_keyboard() -> Dict[str, str]:
    return {
        "first_quarter_moon": "Get QR-code for 2FA app",
        "fountain_pen": "Enter 2FA code",
    }


def get_default_auth_processing_keyboard() -> Dict[str, str]:
    return {
        "fountain_pen": "Enter 2FA code",
    }


def get_default_back_keyboard() -> Dict[str, str]:
    return {"BACK_arrow": "Back to main menu"}


def get_default_bot_commands() -> Dict[str, str]:
    return {
        "/start": "Start bot!",
        "/help": "Get help",
        "/docker": "Launch the section about Docker",
        "/containers": "Get Containers info",
        "/images": "Get Images info",
        "/qrcode": "Get TOTP QR code for 2FA app",
        "/back": "Back to main menu",
        "/check_bot_updates": "Check for software updates",
    }


def get_default_log_levels() -> FrozenSet[str]:
    return frozenset(["ERROR", "INFO", "DEBUG"])


class KeyboardSettings(BaseModel):
    """
    Configuration settings for bot keyboards.

    Attributes:
        main_keyboard (Dict[str, str]): The main keyboard settings.
        server_keyboard (Dict[str, str]): The server keyboard settings.
        docker_keyboard (Dict[str, str]): The Docker keyboard settings.
        auth_keyboard (Dict[str, str]): The authentication keyboard settings.
        auth_processing_keyboard (Dict[str, str]): The keyboard used during authentication.
        back_keyboard (Dict[str, str]): The back navigation keyboard settings.
    """
    main_keyboard: Dict[str, str]
    server_keyboard: Dict[str, str]
    docker_keyboard: Dict[str, str]
    auth_keyboard: Dict[str, str]
    auth_processing_keyboard: Dict[str, str]
    back_keyboard: Dict[str, str]

    model_config = {
        "frozen": True,
        "json_schema_extra": {
            "main_keyboard": get_default_main_keyboard(),
            "server_keyboard": get_default_server_keyboard(),
            "docker_keyboard": get_default_docker_keyboard(),
            "auth_keyboard": get_default_auth_keyboard(),
            "auth_processing_keyboard": get_default_auth_processing_keyboard(),
            "back_keyboard": get_default_back_keyboard(),
        }
    }


class BotCommandSettings(BaseModel):
    """
    Configuration settings for bot commands.

    Attributes:
        bot_commands (Dict[str, str]): The bot commands with descriptions.
    """
    bot_commands: Dict[str, str]

    model_config = {
        "frozen": True,
        "json_schema_extra": {
            "bot_commands": get_default_bot_commands()
        }
    }


class BotDescriptionSettings(BaseModel):
    """
    Configuration settings for the bot description.

    Attributes:
        bot_description (str): The description of the bot.
    """
    bot_description: ClassVar[str] = (
        "pyTMBot - A simple Telegram bot designed to gather basic information "
        "about the status of your local servers"
    )

    model_config = {
        "frozen": True
    }


class VarConfig(BaseModel):
    """
    Configuration settings for various variables used by the bot.

    Attributes:
        template_path (str): Path to the template directory.
        totp_max_attempts (int): Maximum attempts for TOTP authentication.
        bot_polling_timeout (int): Timeout for bot polling.
        bot_long_polling_timeout (int): Timeout for long polling.
    """
    template_path: ClassVar[str] = os.path.join(os.path.dirname(__file__), "templates")
    totp_max_attempts: ClassVar[int] = 3
    bot_polling_timeout: ClassVar[int] = 30
    bot_long_polling_timeout: ClassVar[int] = 60

    model_config = {
        "frozen": True
    }


class LogsSettings(BaseModel):
    """
    Configuration settings for logging.

    Attributes:
        valid_log_levels (FrozenSet[str]): Set of valid log levels.
        bot_logger_format (str): Format of the bot logger output.
    """
    valid_log_levels: FrozenSet[str]
    bot_logger_format: ClassVar[str] = (
        "<green>{time:YYYY-MM-DD}</green> "
        "[<cyan>{time:HH:mm:ss}</cyan>]"
        "[<level>{level: <8}</level>]"
        "[<magenta>{module: <16}</magenta>] › "
        "<level>{message}</level> | {extra}"
    )

    model_config = {
        "frozen": True,
        "json_schema_extra": {
            "valid_log_levels": get_default_log_levels()
        }
    }


# Load settings and configurations
settings = load_settings_from_yaml()
var_config = VarConfig()
keyboard_settings = KeyboardSettings(
    main_keyboard=get_default_main_keyboard(),
    server_keyboard=get_default_server_keyboard(),
    docker_keyboard=get_default_docker_keyboard(),
    auth_keyboard=get_default_auth_keyboard(),
    auth_processing_keyboard=get_default_auth_processing_keyboard(),
    back_keyboard=get_default_back_keyboard()
)
bot_command_settings = BotCommandSettings(bot_commands=get_default_bot_commands())
bot_description_settings = BotDescriptionSettings()
