from __future__ import annotations

import os
from typing import Any

import yaml

from pytmbot import globals as g, logs
from pytmbot.keyboards import keyboards as kb
from pytmbot.middleware.session_manager import SessionManager
from pytmbot.models import handlers_model
from pytmbot.plugins.models import PluginCoreModel


class PluginCore:
    def __init__(self):
        self.settings = g.settings
        self.var_config = g.var_config
        self.bot_logger = logs.bot_logger
        self.keyboard = kb.Keyboards()
        self.handler_models = handlers_model.HandlerManager
        self.session_manager = SessionManager()

    def __get_config_path(self, config_name: str) -> str:
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

        if not os.path.isfile(config_path):
            self.bot_logger.error(f"Config file not found: {config_name}")
            raise FileNotFoundError(f"Config file not found: {config_name}")

        return config_path

    def load_plugin_external_config(
        self, config_name: str, config_model: type[PluginCoreModel]
    ) -> PluginCoreModel:
        """
        Loads plugin external configuration from a YAML file and creates a PluginCoreModel object.

        Args:
            config_name (str): The name of the plugin configuration file.
            config_model (type[PluginCoreModel]): The PluginCoreModel subclass to instantiate.

        Returns:
            PluginCoreModel: An instance of the config_model class with the configuration data.
        """
        config_path = self.__get_config_path(config_name)
        try:
            with open(config_path, "r") as f:
                config_data = yaml.safe_load(f)

            self.bot_logger.debug(f"Loaded plugin config: {config_name}")

            return config_model(**config_data)
        except yaml.YAMLError as err:
            self.bot_logger.error(f"Error parsing YAML file {config_name}: {err}")
            raise
        except Exception as err:
            self.bot_logger.error(f"Error loading plugin config: {err}")
            raise

    def build_plugin_keyboard(self, plugin_keyboard_data: dict[str, str]) -> Any:
        """
        Builds a reply keyboard for the plugin.

        Args:
            plugin_keyboard_data (dict[str, str]): Data to build the keyboard.

        Returns:
            Any: The constructed reply keyboard.
        """
        return self.keyboard.build_reply_keyboard(
            plugin_keyboard_data=plugin_keyboard_data
        )
