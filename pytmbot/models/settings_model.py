#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from typing import Optional

from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings


class BotTokenModel(BaseModel):
    prod_token: list[SecretStr]
    dev_bot_token: Optional[list[SecretStr]]


class AccessControlModel(BaseModel):
    allowed_user_ids: list[int]
    allowed_admins_ids: list[int]
    auth_salt: list[SecretStr]


class DockerHostModel(BaseModel):
    host: list[str]


class SettingsModel(BaseSettings):
    bot_token: BotTokenModel
    access_control: AccessControlModel
    docker: DockerHostModel
