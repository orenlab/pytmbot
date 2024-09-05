#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from typing import Optional, List

from pydantic import BaseModel, SecretStr, conlist
from pydantic_settings import BaseSettings


class BotTokenModel(BaseModel):
    """
    Model for storing bot tokens.

    Attributes:
        prod_token (List[SecretStr]): List of production bot tokens.
        dev_bot_token (Optional[List[SecretStr]]): Optional list of development bot tokens.
    """
    prod_token: conlist(SecretStr, min_length=1)
    dev_bot_token: Optional[conlist(SecretStr, min_length=1)] = None


class AccessControlModel(BaseModel):
    """
    Model for access control settings.

    Attributes:
        allowed_user_ids (List[int]): List of user IDs allowed to access the bot.
        allowed_admins_ids (List[int]): List of admin IDs allowed to access the bot.
        auth_salt (List[SecretStr]): List of salts for authentication.
    """
    allowed_user_ids: conlist(int, min_length=1)
    allowed_admins_ids: conlist(int, min_length=1)
    auth_salt: conlist(SecretStr, min_length=1)


class DockerHostModel(BaseModel):
    """
    Model for Docker host configuration.

    Attributes:
        host (List[str]): List of Docker host addresses.
    """
    host: conlist(str, min_length=1)


class ChatIdModel(BaseModel):
    """
    Model for Telegram chat ID.

    Attributes:
        global_chat_id (Optional[List[int]]): Optional list of Telegram chat IDs used for notifications.
    """
    global_chat_id: Optional[conlist(int, min_length=1)] = None


class TraceholdSettings(BaseModel):
    """
    Model for tracehold settings in the Monitor plugin.

    Attributes:
        cpu_usage_threshold (List[int]): List of CPU usage thresholds in percentage.
        memory_usage_threshold (List[int]): List of memory usage thresholds in percentage.
        disk_usage_threshold (List[int]): List of disk usage thresholds in percentage.
    """
    cpu_usage_threshold: conlist(int, min_length=1, max_length=1) = [80]
    memory_usage_threshold: conlist(int, min_length=1, max_length=1) = [80]
    disk_usage_threshold: conlist(int, min_length=1, max_length=1) = [80]


class MonitorConfig(BaseModel):
    """
    Model for the Monitor plugin configuration.

    Attributes:
        tracehold (TraceholdSettings): Tracehold settings for monitoring.
        max_notifications (List[int]): List of maximum number of notifications to send for each type of overload.
        check_interval (List[int]): List of check intervals in minutes.
        reset_notification_count (List[int]): List of counts after which notifications are reset.
        retry_attempts (List[int]): List of retry attempts.
        retry_interval (List[int]): List of retry intervals in seconds.
    """
    tracehold: TraceholdSettings
    max_notifications: conlist(int, min_length=1, max_length=1) = [3]
    check_interval: conlist(int, min_length=1, max_length=1) = [2]
    reset_notification_count: conlist(int, min_length=1, max_length=1) = [5]
    retry_attempts: conlist(int, min_length=1, max_length=2) = [3]
    retry_interval: conlist(int, min_length=1, max_length=2) = [10]


class OutlineVPN(BaseModel):
    """
    Model for Outline VPN configuration.

    Attributes:
        api_url (List[SecretStr]): List of Outline VPN API URLs.
        cert (List[SecretStr]): List of certificates for Outline VPN.
    """
    api_url: conlist(SecretStr, min_length=1)
    cert: conlist(SecretStr, min_length=1)


class PluginsConfig(BaseModel):
    """
    Model for plugins configuration.

    Attributes:
        monitor (MonitorConfig): Configuration for the Monitor plugin.
        outline (OutlineVPN): Configuration for the Outline VPN plugin.
    """
    monitor: MonitorConfig
    outline: OutlineVPN


class SettingsModel(BaseSettings):
    """
    Model for application settings.

    Attributes:
        bot_token (BotTokenModel): Bot token configuration.
        access_control (AccessControlModel): Access control configuration.
        docker (DockerHostModel): Docker host configuration.
        chat_id (Optional[ChatIdModel]): Optional configuration for Telegram chat IDs.
        plugins_config (Optional[PluginsConfig]): Optional configuration for plugins.
    """
    bot_token: BotTokenModel
    access_control: AccessControlModel
    docker: DockerHostModel
    chat_id: Optional[ChatIdModel] = None
    plugins_config: Optional[PluginsConfig] = None
