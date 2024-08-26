#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>

Outline VPN plugin for pyTMBot

pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

plugin_name = 'outline'
plugin_version = '0.0.1'
plugin_config_name = 'outline.yaml'
plugin_description = 'Outline VPN plugin for pyTMBot'
plugin_commands = ['outline']
plugin_templates = ['outline.jinja2', 'server_info.jinja2', 'keys.jinja2', 'traffic.jinja2']
outline_keyboard: dict[str, str] = {
    'aerial_tramway': 'Server info',
    'books': 'Keys',
    'bullet_train': 'Traffic',
    'BACK_arrow': 'Back to main menu'
}
