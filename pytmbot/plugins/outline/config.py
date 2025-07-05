#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>

Outline VPN plugin for pyTMBot

pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.

This plugin provides commands and templates for interacting with Outline VPN.
"""

from typing import Final

from pytmbot.plugins.models import PluginsPermissionsModel

PLUGIN_NAME = "outline"
PLUGIN_VERSION = "0.0.1"
PLUGIN_DESCRIPTION = "Outline VPN plugin for pyTMBot"
PLUGIN_COMMANDS = {"/outline": "Outline plugin"}
PLUGIN_INDEX_KEY: dict[str, str] = {
    "ringed_planet": "Outline VPN",
}
KEYBOARD: dict[str, str] = {
    "aerial_tramway": "Outline info",
    "books": "Keys",
    "bullet_train": "Traffic",
    "BACK_arrow": "Back to main menu",
}
PLUGIN_PERMISSIONS: Final[PluginsPermissionsModel] = PluginsPermissionsModel(
    base_permission=True,
    need_running_on_host_machine=False,
)
