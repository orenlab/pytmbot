#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from typing import Final

from pytmbot.plugins.models import PluginsPermissionsModel

PLUGIN_NAME = "monitor"
PLUGIN_VERSION = "0.0.6"
PLUGIN_DESCRIPTION = "System monitoring plugin for pyTMBot"
PLUGIN_INDEX_KEY: dict[str, str] = {
    "chart_increasing": "Monitoring",
}
KEYBOARD: dict[str, str] = {
    "gear": "CPU usage",
    "brain": "Memory usage",
    "computer_disk": "Disk usage",
    "thermometer": "Temperatures",
    "BACK_arrow": "Back to main menu",
}
PLUGIN_PERMISSIONS: Final[PluginsPermissionsModel] = PluginsPermissionsModel(
    base_permission=True,
    need_running_on_host_machine=False,
)
