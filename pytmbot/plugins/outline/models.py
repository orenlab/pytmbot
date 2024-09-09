#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>

Outline VPN plugin for pyTMBot

pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from typing import Dict, List, Optional

from pydantic import SecretStr

from pytmbot.plugins.models import PluginCoreModel


class OutlineVPN(PluginCoreModel):
    """Model for Outline VPN config"""

    api_url: list[SecretStr]
    cert: list[SecretStr]


class OutlineConfig(PluginCoreModel):
    """Model for Outline plugin config"""

    outline: OutlineVPN


class OutlineServer(PluginCoreModel):
    """Model for Outline server"""

    name: str
    serverId: str
    metricsEnabled: bool
    createdTimestampMs: int
    version: str
    portForNewAccessKeys: int
    hostnameForAccessKeys: str


class BytesTransferredByUserId(PluginCoreModel):
    """Model for bytes transferred by user id"""

    bytesTransferredByUserId: Dict[str, int]


class OutlineKey(PluginCoreModel):
    """Model for Outline key values"""

    key_id: str
    name: str
    password: str
    port: int
    method: str
    access_url: str
    used_bytes: int
    data_limit: Optional[int]


class OutlineKeys(PluginCoreModel):
    """Model for Outline keys"""

    keys: List[OutlineKey]
