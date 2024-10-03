#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from typing import Optional

from pydantic import BaseModel, SecretStr, conlist
from pydantic_settings import BaseSettings


class BotTokenModel(BaseModel):
    """
    Model to store bot token information for production and development environments.

    Attributes:
        prod_token (List[SecretStr]): List of production bot tokens.
        dev_bot_token (Optional[List[SecretStr]]): Optional list of development bot tokens.
    """

    prod_token: conlist(SecretStr, min_length=1)
    dev_bot_token: Optional[conlist(SecretStr, min_length=1)] = None


class AccessControlModel(BaseModel):
    """
    Model to handle access control settings such as allowed users and admins, and authorization salt.

    Attributes:
        allowed_user_ids (List[int]): List of user IDs that are allowed access.
        allowed_admins_ids (List[int]): List of admin IDs that have elevated permissions.
        auth_salt (List[SecretStr]): List of secret salts for authorization.
    """

    allowed_user_ids: conlist(int, min_length=1)
    allowed_admins_ids: conlist(int, min_length=1)
    auth_salt: conlist(SecretStr, min_length=1)


class DockerHostModel(BaseModel):
    """
    Model to store Docker host information.

    Attributes:
        host (List[str]): List of Docker host URLs or IP addresses.
    """

    host: conlist(str, min_length=1)


class InfluxDBModel(BaseModel):
    """
    Model to store InfluxDB information.

    Attributes:
        url (List[str]): List of InfluxDB URLs.
        token (List[SecretStr]): List of InfluxDB tokens.
        org (List[str]): List of InfluxDB organizations.
        bucket (List[str]): List of InfluxDB buckets.
    """

    url: Optional[conlist(SecretStr, min_length=1)]
    token: Optional[conlist(SecretStr, min_length=1)]
    org: Optional[conlist(SecretStr, min_length=1)]
    bucket: Optional[conlist(SecretStr, min_length=1)]
    debug_mode: bool = False


class ChatIdModel(BaseModel):
    """
    Model to handle optional chat ID configurations for global notifications.

    Attributes:
        global_chat_id (Optional[List[int]]): Optional list of chat IDs for global notifications.
    """

    global_chat_id: conlist(int, min_length=1)


class TraceholdSettings(BaseModel):
    """
    Model to define threshold settings for CPU, memory, and disk usage monitoring.

    Attributes:
        cpu_usage_threshold (List[int]): Threshold for CPU usage in percentage.
        memory_usage_threshold (List[int]): Threshold for memory usage in percentage.
        disk_usage_threshold (List[int]): Threshold for disk usage in percentage.
        cpu_temperature_threshold (List[int]): Threshold for CPU temperature in Celsius.
        gpu_temperature_threshold (List[int]): Threshold for GPU temperature in Celsius.
        disk_temperature_threshold (List[int]): Threshold for disk temperature in Celsius.
    """

    cpu_usage_threshold: conlist(int, min_length=1, max_length=1) = [80]
    memory_usage_threshold: conlist(int, min_length=1, max_length=1) = [80]
    disk_usage_threshold: conlist(int, min_length=1, max_length=1) = [80]
    cpu_temperature_threshold: conlist(int, min_length=1, max_length=1) = [85]
    gpu_temperature_threshold: conlist(int, min_length=1, max_length=1) = [90]
    disk_temperature_threshold: conlist(int, min_length=1, max_length=1) = [60]


class MonitorConfig(BaseModel):
    """
    Model to configure monitoring settings for the bot.

    Attributes:
        tracehold (TraceholdSettings): Threshold settings for resource usage.
        max_notifications (List[int]): Maximum number of notifications before stopping alerts.
        check_interval (List[int]): Interval in minutes between status checks.
        reset_notification_count (List[int]): Time period in minutes to reset the notification count.
        retry_attempts (List[int]): Number of retry attempts for failed status checks.
        retry_interval (List[int]): Interval in minutes between retry attempts.
    """

    tracehold: TraceholdSettings
    max_notifications: conlist(int, min_length=1, max_length=1) = [3]
    check_interval: conlist(int, min_length=1, max_length=1) = [2]
    reset_notification_count: conlist(int, min_length=1, max_length=1) = [5]
    retry_attempts: conlist(int, min_length=1, max_length=2) = [3]
    retry_interval: conlist(int, min_length=1, max_length=2) = [10]


class OutlineVPN(BaseModel):
    """
    Model to store Outline VPN settings.

    Attributes:
        api_url (List[SecretStr]): List of API URLs for Outline VPN.
        cert (List[SecretStr]): List of certificates required for VPN connections.
    """

    api_url: conlist(SecretStr)
    cert: conlist(SecretStr)


class PluginsConfig(BaseModel):
    """
    Model to configure additional plugins for the bot, such as monitoring and Outline VPN.

    Attributes:
        monitor (MonitorConfig): Monitoring configuration settings.
        outline (OutlineVPN): Outline VPN configuration settings.
    """

    monitor: MonitorConfig
    outline: OutlineVPN


class WebhookConfig(BaseModel):
    """
    Model to configure webhook settings for the bot.

    Attributes:
        url (List[SecretStr]): List of webhook URLs.
    """

    url: conlist(SecretStr)
    webhook_port: conlist(int) = [443]
    local_port: conlist(int) = [5001]
    cert: conlist(SecretStr)
    cert_key: conlist(SecretStr)


class SettingsModel(BaseSettings):
    """
    Main settings model for configuring the bot.

    Attributes:
        bot_token (BotTokenModel): Bot token settings for both production and development.
        access_control (AccessControlModel): Access control settings for users and admins.
        docker (DockerHostModel): Docker host settings.
        chat_id (ChatIdModel): Optional chat ID settings for global notifications.
        plugins_config (Optional[PluginsConfig]): Optional plugin configurations (monitoring, VPN).
    """

    bot_token: BotTokenModel
    access_control: AccessControlModel
    docker: DockerHostModel
    chat_id: ChatIdModel
    influxdb: Optional[InfluxDBModel]
    plugins_config: Optional[PluginsConfig]
    webhook_config: Optional[WebhookConfig]
