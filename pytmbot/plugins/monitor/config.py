#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from typing import Final

from pytmbot.plugins.models import PluginsPermissionsModel

PLUGIN_NAME = "monitor"
PLUGIN_VERSION = "0.0.7"
PLUGIN_DESCRIPTION = "System monitoring plugin for pyTMBot"
PLUGIN_INDEX_KEY: dict[str, str] = {
    "chart_increasing": "Monitoring",
}

OVERVIEW_LABEL = "Overview"
CPU_LABEL = "CPU usage"
MEMORY_LABEL = "Memory usage"
DISK_LABEL = "Disk usage"
TEMPERATURES_LABEL = "Temperatures"
SELECT_PERIOD_LABEL = "Select period"
BACK_TO_MONITORING_LABEL = "Back to monitoring"

KEYBOARD: dict[str, str] = {
    "bar_chart": OVERVIEW_LABEL,
    "gear": CPU_LABEL,
    "brain": MEMORY_LABEL,
    "computer_disk": DISK_LABEL,
    "thermometer": TEMPERATURES_LABEL,
    "calendar": SELECT_PERIOD_LABEL,
    "BACK_arrow": "Back to main menu",
}

PERIOD_KEYBOARD: dict[str, str] = {
    "hourglass_not_done": "Last 15 minutes",
    "alarm_clock": "Last 1 hour",
    "mantelpiece_clock": "Last 6 hours",
    "calendar": "Last 24 hours",
    "bar_chart": "Last 7 days",
    "BACK_arrow": BACK_TO_MONITORING_LABEL,
}

PERIOD_PRESETS: dict[str, dict[str, str]] = {
    "15m": {"label": "Last 15 minutes", "start": "-15m"},
    "1h": {"label": "Last 1 hour", "start": "-1h"},
    "6h": {"label": "Last 6 hours", "start": "-6h"},
    "24h": {"label": "Last 24 hours", "start": "-24h"},
    "7d": {"label": "Last 7 days", "start": "-7d"},
}

PERIOD_LABEL_TO_KEY: dict[str, str] = {
    preset["label"]: period_key for period_key, preset in PERIOD_PRESETS.items()
}

DEFAULT_PERIOD_KEY = "1h"

METRIC_LABEL_TO_KEY: dict[str, str] = {
    OVERVIEW_LABEL: "overview",
    CPU_LABEL: "cpu",
    MEMORY_LABEL: "memory",
    DISK_LABEL: "disk",
    TEMPERATURES_LABEL: "temperature",
}

PLUGIN_PERMISSIONS: Final[PluginsPermissionsModel] = PluginsPermissionsModel(
    base_permission=True,
    need_running_on_host_machine=False,
)
