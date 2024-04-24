DEFAULT_BOT_SETTINGS = '''#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local computers and/or servers from Glances
"""
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class BotSettings:
    """Add your telegram IDs. And your bot too!"""
    ALLOWED_USER_IDS: list = [$user_id]


class DockerSettings:
    """Set Docker Socket o TCP param. Default """
    docker_host: str = '$docker_host'


class BotTokenSettings(BaseSettings):
    """Bot Token Settings. Get token from CLI"""
    bot_token: SecretStr
    dev_bot_token: SecretStr
    model_config = SettingsConfigDict(env_file='.env', env_file_encoding='utf-8')


token_settings = BotTokenSettings()
'''
