#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
import os.path
from typing import List

from telebot import TeleBot


class PluginLoader:

    def __init__(self, plugin_name, plugin_version, plugin_description, plugin_commands, plugin_keyboards,
                 plugin_templates):
        self.bot = TeleBot
        self.plugin_name: str = plugin_name
        self.plugin_version: str = plugin_version
        self.plugin_description: str = plugin_description
        self.plugin_commands: List[str] = plugin_commands
        self.plugin_keyboards: List[str] = plugin_keyboards
        self.plugin_templates: List[str] = plugin_templates
        self.plugins = []
        self.plugins_list = []

    @property
    def __is_plugin_available(self):
        return os.path.exists(self.plugin_name)

    def load_plugins(self):
        """Loads plugins from plugins folder"""
        if self.__is_plugin_available:
            self.plugins_list.append(self.plugin_name)

        for plugin in self.plugins_list:
            self.plugins.append(self.plugins[plugin])

        return self.plugins
