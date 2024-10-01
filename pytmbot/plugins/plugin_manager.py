import importlib
import importlib.util
import inspect
import re
from dataclasses import dataclass
from typing import List, Type, Optional

from telebot import TeleBot

from pytmbot.logs import bot_logger
from pytmbot.plugins.models import PluginsPermissionsModel
from pytmbot.plugins.plugin_interface import PluginInterface
from pytmbot.utils.utilities import is_running_in_docker


@dataclass
class _PluginInfo:
    """
    Stores metadata for a plugin, including its name, version, description, commands, and index key.

    Attributes:
        name (str): The name of the plugin.
        version (str): The version of the plugin.
        description (str): A brief description of the plugin.
        commands (Optional[dict[str, str]]): A dictionary mapping command names to descriptions.
        index_key (Optional[dict[str, str]]): A dictionary mapping index keys to descriptions.
    """

    name: str
    version: str
    description: str
    commands: Optional[dict[str, str]] = None
    index_key: Optional[dict[str, str]] = None


class PluginManager:
    """
    Manages the discovery, validation, and registration of plugins in the pyTMBot system.

    This singleton class handles the loading and registration of plugins, validates plugin names,
    and manages metadata about registered plugins.

    Attributes:
        _instance (Optional[PluginManager]): The singleton instance of the class.
        _index_keys (dict[str, str]): A dictionary storing index keys for all registered plugins.
        _plugin_names (dict[str, str]): A dictionary storing the names and versions of all registered plugins.
        _plugin_descriptions (dict[str, str]): A dictionary storing descriptions for all registered plugins.
    """

    _instance = None
    _index_keys = {}
    _plugin_names = {}
    _plugin_descriptions = {}

    def __new__(cls, *args, **kwargs) -> "PluginManager":
        """
        Creates or retrieves the singleton instance of the PluginManager.

        Returns:
            PluginManager: The singleton instance of the class.
        """
        if cls._instance is None:
            cls._instance = super(PluginManager, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    @staticmethod
    def _validate_plugin_name(plugin_name: str) -> bool:
        """
        Validates the plugin name against a predefined pattern.

        Args:
            plugin_name (str): The name of the plugin to validate.

        Returns:
            bool: True if the name is valid, False otherwise.
        """
        valid_plugin_name_pattern = re.compile(r"^[a-z_]+$")
        return bool(valid_plugin_name_pattern.match(plugin_name))

    @staticmethod
    def _module_exists(plugin_name: str) -> bool:
        """
        Checks if the module for the given plugin name exists.

        Args:
            plugin_name (str): The name of the plugin to check.

        Returns:
            bool: True if the module exists, False otherwise.
        """
        module_path = f"pytmbot.plugins.{plugin_name}.config"
        return importlib.util.find_spec(module_path) is not None

    @staticmethod
    def _import_module(plugin_name: str):
        """
        Imports the plugin module.

        Args:
            plugin_name (str): The name of the plugin module to import.

        Returns:
            module: The imported module.

        Raises:
            ImportError: If the module cannot be imported.
        """
        module_path = f"pytmbot.plugins.{plugin_name}.plugin"
        try:
            return importlib.import_module(module_path)
        except ImportError as e:
            bot_logger.error(f"ImportError: {e} - Module path: {module_path}")
            raise

    @staticmethod
    def _import_module_config(plugin_name: str):
        """
        Dynamically imports the plugin configuration module.

        Args:
            plugin_name (str): The name of the plugin configuration module to import.

        Returns:
            module: The imported configuration module.

        Raises:
            ImportError: If the configuration module cannot be imported.
        """
        module_path = f"pytmbot.plugins.{plugin_name}.config"
        try:
            return importlib.import_module(module_path)
        except ImportError as e:
            bot_logger.error(f"Failed to import plugin config '{plugin_name}': {e}")
            raise

    @staticmethod
    def _find_plugin_classes(module) -> List[Type[PluginInterface]]:
        """
        Finds and returns all valid plugin classes in the given module.

        Args:
            module: The module to search for plugin classes.

        Returns:
            List[Type[PluginInterface]]: A list of plugin classes found in the module.
        """
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
    def _extract_plugin_permissions(module) -> PluginsPermissionsModel:
        """
        Extracts the permission settings for the plugin from its configuration module.

        Args:
            module: The plugin configuration module to extract permissions from.

        Returns:
            PluginsPermissionsModel: A permission model object for the plugin.
        """
        permissions = getattr(module, "PLUGIN_PERMISSIONS", None)

        if not isinstance(permissions, PluginsPermissionsModel):
            bot_logger.error(f"Invalid permissions model in plugin '{module.__name__}'")
            raise ValueError(
                f"Invalid permissions model for plugin '{module.__name__}'"
            )

        return permissions

    def _extract_plugin_info(self, module) -> _PluginInfo | None:
        """
        Extracts necessary plugin configuration details from the given module,
        including permissions and environment requirements.

        Args:
            module: The plugin module from which to extract configuration details.

        Returns:
            _PluginInfo: A dataclass containing the plugin's configuration if valid, None otherwise.
        """
        try:
            name = getattr(module, "PLUGIN_NAME")
            version = getattr(module, "PLUGIN_VERSION")
            description = getattr(module, "PLUGIN_DESCRIPTION")
            commands = getattr(module, "PLUGIN_COMMANDS", None)
            index_key = getattr(module, "PLUGIN_INDEX_KEY", None)
            permissions = self._extract_plugin_permissions(module)

            # Check if the plugin requires running on a host machine
            if permissions.need_running_on_host_machine and is_running_in_docker():
                bot_logger.warning(
                    f"Plugin '{name}' requires host environment. Skipping registration in Docker container."
                )
                return None

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
        """
        Adds information about a plugin to the internal management structures.

        Args:
            plugin_info (_PluginInfo): The information about the plugin to add.
        """
        if plugin_info:
            if plugin_info.index_key:
                cls._index_keys.update(plugin_info.index_key)
            cls._plugin_names[plugin_info.name] = plugin_info.version
            cls._plugin_descriptions[plugin_info.name] = plugin_info.description

    @classmethod
    def get_merged_index_keys(cls) -> dict[str, str]:
        """
        Retrieves the merged index keys for all registered plugins.

        Returns:
            dict[str, str]: A dictionary of index keys and their descriptions.
        """
        return cls._index_keys

    @classmethod
    def get_plugin_names(cls) -> dict[str, str]:
        """
        Retrieves the names and versions of all registered plugins.

        Returns:
            dict[str, str]: A dictionary of plugin names and their versions.
        """
        return cls._plugin_names

    @classmethod
    def get_plugin_descriptions(cls) -> dict[str, str]:
        """
        Retrieves the descriptions of all registered plugins.

        Returns:
            dict[str, str]: A dictionary of plugin names and their descriptions.
        """
        return cls._plugin_descriptions

    def _register_plugin(self, plugin_name: str, bot: Optional[TeleBot] = None):
        """
        Registers a single plugin by its name, considering its permissions and sandbox environment.

        Args:
            plugin_name (str): The name of the plugin to register.
            bot (Optional[TeleBot]): The bot instance to which the plugin will be registered. Defaults to None.
        """
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

            permissions: PluginsPermissionsModel = self._extract_plugin_permissions(
                config
            )

            self.add_plugin_info(plugin_info)

            plugin_classes = self._find_plugin_classes(module)
            if not plugin_classes:
                bot_logger.error(f"No valid plugin class found in '{plugin_name}'.")
                return

            plugin_instance = plugin_classes[0](bot)

            # Ensure that commands are executed in the sandbox
            if permissions.base_permission:
                plugin_instance.register()

                bot_logger.info(
                    f"Plugin '{plugin_info.name}' (v{plugin_info.version}) registered successfully."
                )
            else:
                bot_logger.warning(
                    f"Plugin '{plugin_info.name}' does not have permission to execute commands. Skipping registration."
                )

        except Exception as error:
            bot_logger.exception(
                f"Unexpected error registering plugin '{plugin_name}': {error}"
            )

    def register_plugins(self, plugin_names: List[str], bot: Optional[TeleBot] = None):
        """
        Registers multiple plugins by their names.

        Args:
            plugin_names (List[str]): A list of plugin names to register.
            bot (Optional[TeleBot]): The bot instance to which the plugins will be registered. Defaults to None.
        """
        plugins_to_register = [
            name.strip() for plugin in plugin_names for name in plugin.split(",")
        ]

        for plugin_name in plugins_to_register:
            if plugin_name:
                self._register_plugin(plugin_name, bot)
            else:
                bot_logger.warning("Plugin name is empty. Skipping...")
