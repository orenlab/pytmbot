#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local computers and/or servers from Glances
"""
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    """Bot Settings.
    """
    bot_token: SecretStr  # Bot toke from .pytmbotenv
    dev_bot_token: SecretStr  # Dev bot toke from .pytmbotenv
    allowed_user_ids: list[int]  # Allowed user id from .pytmbotenv
    docker_host: str  # Docker socket URI from .pytmbotenv
    podman_host: str  # Podman socker URI from .pytmbotenv
    model_config = SettingsConfigDict(env_file='.pytmbotenv', env_file_encoding='utf-8')
