#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from pydantic import SecretStr

from pytmbot.plugins.models import PluginCoreModel


class OutlineVPN(PluginCoreModel):
    """Model for Outline VPN config"""

    api_url: list[SecretStr]
    cert: list[SecretStr]
    verify_tls: bool = True
