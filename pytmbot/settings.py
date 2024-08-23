#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import os
from functools import lru_cache
from typing import List, FrozenSet

import yaml
from pydantic import BaseModel

from pytmbot.models.settings_model import SettingsModel


def get_env_file_path() -> str:
    # Get the current directory
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # Navigate to the root directory
    root_dir = os.path.dirname(current_dir)

    # Construct the path to the .pytmbotenv file
    env_file_path = os.path.join(root_dir, 'pytmbot.yaml')

    return env_file_path


@lru_cache(maxsize=None)
def load_settings_from_yaml() -> SettingsModel:
    try:
        with open(get_env_file_path(), 'r') as f:
            settings_data = yaml.safe_load(f)
        return SettingsModel(**settings_data)
    except FileNotFoundError:
        raise FileNotFoundError("pytmbot.yaml not found")


class VarConfig(BaseModel):
    # Set local configuration
    bot_commands: dict[str, str] = {
        "/start": "Start bot!",
        "/help": "Get help",
        "/docker": "Launch the section about Docker",
        "/containers": "Get Containers info",
        "/images": "Get Images info",
        "/qrcode": "Get TOTP QR code for 2FA app",
        "/back": "Back to main menu",
        "/check_bot_updates": "Check for software updates",
    }
    description: str = (
        "pyTMBot - A simple Telegram bot designed to gather basic information about the status of your local servers"
    )
    template_path: str = os.path.join(os.path.dirname(__file__), 'templates')
    known_templates: List[str] = [
        'd_containers.jinja2',
        'b_fs.jinja2',
        'b_index.jinja2',
        'b_load_average.jinja2',
        'b_memory.jinja2',
        'b_none.jinja2',
        'b_process.jinja2',
        'b_sensors.jinja2',
        'b_uptime.jinja2',
        'b_bot_update.jinja2',
        'b_swap.jinja2',
        'b_how_update.jinja2',
        'b_net_io.jinja2',
        'b_about_bot.jinja2',
        'd_containers_full_info.jinja2',
        'd_logs.jinja2',
        'd_docker.jinja2',
        'b_back.jinja2',
        'd_images.jinja2',
        'a_auth_required.jinja2',
        'd_managing_containers.jinja2',
        'a_send_totp_code.jinja2',
        'b_echo.jinja2',
        'a_access_denied.jinja2',
        'a_success.jinja2'
    ]
    main_keyboard: dict[str, str] = {
        'low_battery': 'Load average',
        'pager': 'Memory load',
        'stopwatch': 'Sensors',
        'rocket': 'Process',
        'flying_saucer': 'Uptime',
        'floppy_disk': 'File system',
        'spouting_whale': 'Docker',
        'satellite': 'Network',
        'turtle': 'About me'
    }
    docker_keyboard: dict[str, str] = {
        'framed_picture': 'Images',
        'toolbox': 'Containers',
        'BACK_arrow': 'Back to main menu'
    }
    auth_keyboard: dict[str, str] = {
        'first_quarter_moon': 'Get QR-code for 2FA app',
        'fountain_pen': 'Enter 2FA code',
        'BACK_arrow': 'Back to main menu'
    }
    auth_processing_keyboard: dict[str, str] = {
        'fountain_pen': 'Enter 2FA code',
        'BACK_arrow': 'Back to main menu'
    }
    back_keyboard: dict[str, str] = {
        'BACK_arrow': 'Back to main menu'
    }
    totp_max_attempts: int = 3
    bot_polling_timeout: int = 30
    bot_long_polling_timeout: int = 60


class LogsSettings(BaseModel):
    valid_log_levels: FrozenSet[str] = frozenset(['ERROR', 'INFO', 'DEBUG'])
    bot_logger_format: str = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | <level>{message}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan>"
    )


settings = load_settings_from_yaml()
var_config = VarConfig()
log_settings = LogsSettings()
