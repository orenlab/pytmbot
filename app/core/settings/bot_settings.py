#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local computers and/or servers from Glances
"""
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings(BaseSettings):
    """Bot Settings. Get token from .pytmbotenv"""
    bot_token: SecretStr
    dev_bot_token: SecretStr
    allowed_user_ids: list[int]
    docker_host: str
    podman_host: str
    model_config = SettingsConfigDict(env_file='.pytmbotenv', env_file_encoding='utf-8')
