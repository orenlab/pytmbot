import importlib
import importlib.util
import inspect
import re
from dataclasses import dataclass
from typing import List, Type, Optional

from telebot import TeleBot

from pytmbot.logs import bot_logger
from pytmbot.plugins.plugin_interface import PluginInterface


@dataclass
class _PluginInfo:
    """Stores plugin metadata for registration and management."""

    name: str
    version: str
    description: str
    commands: Optional[dict[str, str]] = None
    index_key: Optional[dict[str, str]] = None


class PluginManager:
    """
    Manages the discovery, validation, and registration of plugins in the pyTMBot system.
    """

    _instance = None
    _index_keys = {}
    _plugin_names = {}
    _plugin_descriptions = {}

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(PluginManager, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    @staticmethod
    def _validate_plugin_name(plugin_name: str) -> bool:
        """Check if the plugin name is valid based on a predefined pattern."""
        valid_plugin_name_pattern = re.compile(r"^[a-z_]+$")
        return bool(valid_plugin_name_pattern.match(plugin_name))

    @staticmethod
    def _module_exists(plugin_name: str) -> bool:
        """Check if the module for the given plugin name exists."""
        module_path = f"pytmbot.plugins.{plugin_name}.config"
        return importlib.util.find_spec(module_path) is not None

    @staticmethod
    def _import_module(plugin_name: str):
        """Import the module for the given plugin name."""
        module_path = f"pytmbot.plugins.{plugin_name}.plugin"
        try:
            return importlib.import_module(module_path)
        except ImportError as e:
            bot_logger.error(f"ImportError: {e} - Module path: {module_path}")
            raise

    @staticmethod
    def _import_module_config(plugin_name: str):
        """Dynamically import the plugin configuration module."""
        module_path = f"pytmbot.plugins.{plugin_name}.config"
        try:
            return importlib.import_module(module_path)
        except ImportError as e:
            bot_logger.error(f"Failed to import plugin config '{plugin_name}': {e}")
            raise

    @staticmethod
    def _find_plugin_classes(module) -> List[Type[PluginInterface]]:
        """Find and return all valid plugin classes in the module."""
        plugin_classes = []
        for attribute_name in dir(module):
            attr = getattr(module, attribute_name)
            if (
                inspect.isclass(attr)
                and issubclass(attr, PluginInterface)
                and attr is not PluginInterface
            ):
                plugin_classes.append(attr)
        return plugin_classes

    @staticmethod
    def _extract_plugin_info(module) -> Optional[_PluginInfo]:
        """
        Extract necessary plugin configuration details.

        Args:
            module: The plugin module.

        Returns:
            _PluginInfo: A dataclass containing the plugin's configuration if valid.
        """
        try:
            name = getattr(module, "PLUGIN_NAME")
            version = getattr(module, "PLUGIN_VERSION")
            description = getattr(module, "PLUGIN_DESCRIPTION")
            commands = getattr(module, "PLUGIN_COMMANDS", None)
            index_key = getattr(module, "PLUGIN_INDEX_KEY", None)

            return _PluginInfo(
                name=name,
                version=version,
                description=description,
                commands=commands,
                index_key=index_key,
            )
        except AttributeError as e:
            bot_logger.error(f"Plugin config error: missing required attributes - {e}")
            return None

    @classmethod
    def add_plugin_info(cls, plugin_info: _PluginInfo):
        if plugin_info:
            if plugin_info.index_key:
                cls._index_keys.update(plugin_info.index_key)
            cls._plugin_names[plugin_info.name] = plugin_info.version
            cls._plugin_descriptions[plugin_info.name] = plugin_info.description

    @classmethod
    def get_merged_index_keys(cls) -> dict[str, str]:
        return cls._index_keys

    @classmethod
    def get_plugin_names(cls) -> dict[str, str]:
        return cls._plugin_names

    @classmethod
    def get_plugin_descriptions(cls) -> dict[str, str]:
        return cls._plugin_descriptions

    def _register_plugin(self, plugin_name: str, bot: Optional[TeleBot] = None):
        """Register a single plugin."""
        bot_logger.debug(f"Attempting to register plugin: '{plugin_name}'")

        if not self._validate_plugin_name(plugin_name):
            bot_logger.error(f"Invalid plugin name: '{plugin_name}'. Skipping.")
            return

        if not self._module_exists(plugin_name):
            bot_logger.error(f"Plugin '{plugin_name}' not found. Skipping.")
            return

        try:
            module = self._import_module(plugin_name)
            config = self._import_module_config(plugin_name)

            plugin_info = self._extract_plugin_info(config)
            if not plugin_info:
                bot_logger.error(f"Invalid plugin configuration for '{plugin_name}'.")
                return

            self.add_plugin_info(plugin_info)

            plugin_classes = self._find_plugin_classes(module)
            if not plugin_classes:
                bot_logger.error(f"No valid plugin class found in '{plugin_name}'.")
                return

            plugin_instance = plugin_classes[0](bot)
            plugin_instance.register()

            bot_logger.info(
                f"Plugin '{plugin_info.name}' (v{plugin_info.version}) registered successfully."
            )

        except Exception as error:
            bot_logger.exception(
                f"Unexpected error registering plugin '{plugin_name}': {error}"
            )

    def register_plugins(self, plugin_names: List[str], bot: Optional[TeleBot] = None):
        """
        Register multiple plugins.

        Args:
            plugin_names (List[str]): A list of plugin names.
            bot (TeleBot, optional): The bot instance to which the plugins will be registered. Defaults to None.
        """
        plugins_to_register = [
            name.strip() for plugin in plugin_names for name in plugin.split(",")
        ]

        for plugin_name in plugins_to_register:
            if plugin_name:
                self._register_plugin(plugin_name, bot)
            else:
                bot_logger.warning("Plugin name is empty. Skipping...")
