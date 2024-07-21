#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local computers and/or servers from Glances
"""
import os
from typing import Optional

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# Bot commands model
command_model = {
    "/start": "Start bot!",
    "/help": "Get help",
    "/docker": "Launch the section about Docker",
    "/containers": "Get Containers info",
    "/images": "Get Images info",
    "/back": "Back to main menu",
    "/check_bot_updates": "Check for software updates",
}


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
    BotSettings class to load configuration from .pytmbotenv file

    Attributes:
        bot_token: SecretStr  # Bot toke from .pytmbotenv
        dev_bot_token: Optional[SecretStr]  # Dev bot toke from .pytmbotenv
        allowed_user_ids: list[int]  # Allowed user id from .pytmbotenv
        docker_host: str  # Docker socket URI from .pytmbotenv
        podman_host: Optional[str]  # Podman socker URI from .pytmbotenv
    """

    bot_token: SecretStr  # Bot toke from .pytmbotenv
    dev_bot_token: Optional[SecretStr]  # Dev bot toke from .pytmbotenv
    allowed_user_ids: list[int]  # Allowed user id from .pytmbotenv
    docker_host: str  # Docker socket URI from .pytmbotenv
    podman_host: Optional[str]  # Podman socker URI from .pytmbotenv
    model_config = SettingsConfigDict(env_file=get_env_file_path(), env_file_encoding='utf-8')
    bot_commands: dict = command_model
