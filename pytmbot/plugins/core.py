#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
from __future__ import annotations

import os

import yaml

from pytmbot.globals import settings, var_config
from pytmbot.logs import bot_logger
from pytmbot.plugins.models import PluginCoreModel


class PluginCore:
    def __init__(self):
        self.settings = settings
        self.var_config = var_config
        self.bot_logger = bot_logger

    @staticmethod
    def __get_config_path(config_name: str) -> str:
        """
        Returns the absolute path to the config file.

        Args:
            config_name (str): The name of the config file.

        Returns:
            str: The absolute path to the config file.
        """

        current_dir = os.path.dirname(__file__)
        parent_dir = os.path.dirname(current_dir)
        grandparent_dir = os.path.dirname(parent_dir)
        config_path = os.path.join(grandparent_dir, config_name)
        return config_path

    def load_plugin_config(self, config_name: str, config_model: type[PluginCoreModel]):
        """
        Loads plugin configuration from a YAML file and creates a PluginCoreModel object.

        Args:
            config_name (str): The name of the plugin configuration file.
            config_model (type[PluginCoreModel]): The PluginCoreModel subclass to instantiate.

        Returns:
            PluginCoreModel: An instance of the config_model class with the configuration data.
        """
        config_path = self.__get_config_path(config_name)
        with open(config_path, 'r') as f:
            config_data = yaml.safe_load(f)

        return config_model(**config_data)
