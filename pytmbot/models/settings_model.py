#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from typing import Optional, List

from pydantic import BaseModel, SecretStr
from pydantic_settings import BaseSettings


class BotTokenModel(BaseModel):
    """
    Model for storing bot tokens.

    Attributes:
        prod_token (List[SecretStr]): List of production bot tokens.
        dev_bot_token (Optional[List[SecretStr]]): Optional list of development bot tokens.
    """
    prod_token: List[SecretStr]
    dev_bot_token: Optional[List[SecretStr]]


class AccessControlModel(BaseModel):
    """
    Model for access control settings.

    Attributes:
        allowed_user_ids (List[int]): List of user IDs allowed to access the bot.
        allowed_admins_ids (List[int]): List of admin IDs allowed to access the bot.
        auth_salt (List[SecretStr]): List of salts for authentication.
    """
    allowed_user_ids: List[int]
    allowed_admins_ids: List[int]
    auth_salt: List[SecretStr]


class DockerHostModel(BaseModel):
    """
    Model for Docker host configuration.

    Attributes:
        host (List[str]): List of Docker host addresses.
    """
    host: List[str]


class SettingsModel(BaseSettings):
    """
    Model for application settings.

    Attributes:
        bot_token (BotTokenModel): Bot token configuration.
        access_control (AccessControlModel): Access control configuration.
        docker (DockerHostModel): Docker host configuration.
    """
    bot_token: BotTokenModel
    access_control: AccessControlModel
    docker: DockerHostModel
