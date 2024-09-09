#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>

Outline VPN plugin for pyTMBot

pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.

This plugin provides commands and templates for interacting with Outline VPN.
"""

PLUGIN_NAME = "outline"
PLUGIN_VERSION = "0.0.1"
PLUGIN_DESCRIPTION = "Outline VPN plugin for pyTMBot"
PLUGIN_COMMANDS = {"/outline": "Outline plugin"}
PLUGIN_TEMPLATES = [
    "outline.jinja2",
    "server_info.jinja2",
    "keys.jinja2",
    "traffic.jinja2",
]

OUTLINE_KEYBOARD: dict[str, str] = {
    "aerial_tramway": "Server info",
    "books": "Keys",
    "bullet_train": "Traffic",
    "BACK_arrow": "Back to main menu",
}
