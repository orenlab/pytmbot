#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
import os
from typing import Optional, List, FrozenSet

from pydantic import SecretStr, BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


def get_env_file_path() -> str:
    """
    Get the path of the .pytmbotenv file.

    This function navigates through the directory structure to find the root directory
    and then constructs the path to the .pytmbotenv file.

    Returns:
        str: The path of the .pytmbotenv file.
    """
    # Get the current directory
    current_dir = os.path.dirname(os.path.abspath(__file__))

    # Navigate to the parent directory
    parent_dir = os.path.dirname(current_dir)

    # Navigate to the grandparent directory
    grandparent_dir = os.path.dirname(parent_dir)

    # Navigate to the root directory
    root_dir = os.path.dirname(grandparent_dir)

    # Construct the path to the .pytmbotenv file
    env_file_path = os.path.join(root_dir, '.pytmbotenv')

    return env_file_path


class BotSettings(BaseSettings):
    """
    BotSettings class to load configuration from .pytmbotenv file and settings variables
    """

    bot_token: SecretStr  # Bot toke from .pytmbotenv
    dev_bot_token: Optional[SecretStr]  # Dev bot toke from .pytmbotenv
    allowed_user_ids: list[int]  # Allowed user id from .pytmbotenv
    allowed_admins_ids: Optional[list[int]]  # Allowed admin ids from .pytmbotenv
    docker_host: str  # Docker socket URI from .pytmbotenv
    auth_salt: Optional[SecretStr] = SecretStr  # Auth salt
    model_config = SettingsConfigDict(env_file=get_env_file_path(), env_file_encoding='utf-8')
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
        'a_totp_code_verified.jinja2',
        'a_totp_code_not_verified.jinja2',
        'a_access_denied.jinja2'
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


class LogsSettings(BaseModel):
    valid_log_levels: FrozenSet[str] = frozenset(['ERROR', 'INFO', 'DEBUG'])
    bot_logger_format: str = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | <level>{message}</level> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan>"
    )
