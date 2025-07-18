#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import importlib
import importlib.util
import inspect
import re
import weakref
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import List, Type, Optional, Dict, Set

from telebot import TeleBot

from pytmbot.logs import Logger
from pytmbot.plugins.models import PluginsPermissionsModel
from pytmbot.plugins.plugin_interface import PluginInterface
from pytmbot.utils import is_running_in_docker

logger = Logger()


@dataclass(slots=True)
class _PluginInfo:
    """
    Stores metadata for a plugin, including its name, version, description, commands, and index key.

    Attributes:
        name (str): The name of the plugin.
        version (str): The version of the plugin.
        description (str): A brief description of the plugin.
        commands (Optional[dict[str, str]]): A dictionary mapping command names to descriptions.
        index_key (Optional[dict[str, str]]): A dictionary mapping index keys to descriptions.
        resource_limits (dict): Resource limits for the plugin (memory, CPU, etc.)
    """

    name: str
    version: str
    description: str
    commands: Optional[dict[str, str]] = None
    index_key: Optional[dict[str, str]] = None
    resource_limits: dict = None

    def __post_init__(self):
        if self.resource_limits is None:
            self.resource_limits = {
                "max_memory_mb": 100,
                "max_cpu_percent": 50,
                "execution_timeout_sec": 30,
            }


class PluginManager:
    """
    Manages the discovery, validation, and registration of plugins in the pyTMBot system.
    """

    __slots__ = ("_plugin_base_path", "_plugin_base_for_import", "_plugin_blacklist")

    _instance = None
    _index_keys: Dict[str, str] = {}
    _plugin_names: Dict[str, str] = {}
    _plugin_descriptions: Dict[str, str] = {}
    _plugin_instances: Dict[str, weakref.ref] = {}
    _loaded_plugins: Set[str] = set()

    _plugin_resources = {
        "default_limits": {
            "max_memory_mb": 100,
            "max_cpu_percent": 50,
            "execution_timeout_sec": 30,
        }
    }

    def __new__(cls, *args, **kwargs) -> "PluginManager":
        """Creates or retrieves the singleton instance of the PluginManager."""
        if cls._instance is None:
            try:
                if cls._instance is None:
                    cls._instance = super(PluginManager, cls).__new__(cls)
                    cls._instance._initialize()
            except Exception as e:
                logger.error(f"Failed to create PluginManager instance: {e}")
        return cls._instance

    def _initialize(self):
        """Initialize the plugin manager instance."""
        self._plugin_base_path = Path("pytmbot/plugins")
        self._plugin_base_for_import = "pytmbot.plugins"
        self._load_blacklist()

    def _load_blacklist(self):
        """Load blacklisted plugin patterns and names."""
        self._plugin_blacklist = {
            "patterns": [
                r".*\/.*",  # Prevent directory traversal
                r"^\..*",  # Prevent hidden files
                r".*\.py$",  # Prevent direct Python file loading
            ],
            "names": {"__pycache__", "tests", "examples"},
        }

    @staticmethod
    @lru_cache(maxsize=128)
    def _validate_plugin_name(plugin_name: str) -> bool:
        """Validates the plugin name against security patterns."""
        if not isinstance(plugin_name, str):
            return False

        valid_plugin_name_pattern = re.compile(r"^[a-z_]+$")
        if not bool(valid_plugin_name_pattern.match(plugin_name)):
            return False

        security_patterns = [
            r"\.\.",  # Path traversal
            r"[\/\\]",  # Directory separators
            r"[;&|]",  # Command injection chars
            r"\s",  # Whitespace
        ]

        return not any(re.search(pattern, plugin_name) for pattern in security_patterns)

    def _validate_plugin_path(self, plugin_name: str) -> bool:
        """Validates that the plugin path is within the allowed directory."""
        try:
            plugin_path = (self._plugin_base_path / plugin_name).resolve()
            base_path = self._plugin_base_path.resolve()
            return base_path in plugin_path.parents
        except (ValueError, RuntimeError):
            return False

    @lru_cache(maxsize=128)
    def _module_exists(self, plugin_name: str) -> bool:
        """Checks if the module exists."""
        module_path = f"{self._plugin_base_for_import}.{plugin_name}.config"
        return importlib.util.find_spec(module_path) is not None

    def _import_module(self, plugin_name: str):
        """Safely imports the plugin module."""
        if not self._validate_plugin_path(plugin_name):
            raise ImportError(f"Plugin path validation failed for '{plugin_name}'")

        module_path = f"{self._plugin_base_for_import}.{plugin_name}.plugin"
        try:
            return importlib.import_module(module_path)
        except ImportError as e:
            logger.error(f"ImportError: {e} - Module path: {module_path}")
            raise

    def _import_module_config(self, plugin_name: str):
        """Safely imports the plugin configuration module."""
        if not self._validate_plugin_path(plugin_name):
            raise ImportError(
                f"Plugin config path validation failed for '{plugin_name}'"
            )

        module_path = f"{self._plugin_base_for_import}.{plugin_name}.config"
        try:
            return importlib.import_module(module_path)
        except ImportError as e:
            logger.error(f"Failed to import plugin config '{plugin_name}': {e}")
            raise

    @staticmethod
    def _find_plugin_classes(module) -> List[Type[PluginInterface]]:
        """Finds all valid plugin classes in the module."""
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
        """Extracts and validates plugin permissions."""
        permissions = getattr(module, "PLUGIN_PERMISSIONS", None)

        if not isinstance(permissions, PluginsPermissionsModel):
            logger.error(f"Invalid permissions model in plugin '{module.__name__}'")
            raise ValueError(
                f"Invalid permissions model for plugin '{module.__name__}'"
            )

        if not hasattr(permissions, "base_permission"):
            raise ValueError("Missing base_permission in plugin permissions")

        return permissions

    def _extract_plugin_info(self, module) -> Optional[_PluginInfo]:
        """Extracts and validates plugin configuration details."""
        try:
            required_attrs = ["PLUGIN_NAME", "PLUGIN_VERSION", "PLUGIN_DESCRIPTION"]
            for attr in required_attrs:
                if not hasattr(module, attr):
                    raise AttributeError(f"Missing required attribute: {attr}")

            name = getattr(module, "PLUGIN_NAME")
            version = getattr(module, "PLUGIN_VERSION")
            description = getattr(module, "PLUGIN_DESCRIPTION")
            commands = getattr(module, "PLUGIN_COMMANDS", None)
            index_key = getattr(module, "PLUGIN_INDEX_KEY", None)

            resource_limits = getattr(
                module,
                "PLUGIN_RESOURCE_LIMITS",
                self._plugin_resources["default_limits"].copy(),
            )

            permissions = self._extract_plugin_permissions(module)

            if permissions.need_running_on_host_machine and is_running_in_docker():
                logger.warning(
                    f"Plugin '{name}' requires host environment. Skipping registration in Docker container."
                )
                return None

            return _PluginInfo(
                name=name,
                version=version,
                description=description,
                commands=commands,
                index_key=index_key,
                resource_limits=resource_limits,
            )
        except AttributeError as e:
            logger.error(f"Plugin config error: missing required attributes - {e}")
            return None

    @classmethod
    def add_plugin_info(cls, plugin_info: _PluginInfo) -> bool:
        """Safely adds plugin information to internal structures."""
        if not plugin_info:
            return False

        try:
            if plugin_info.index_key:
                cls._index_keys.update(plugin_info.index_key)
            cls._plugin_names[plugin_info.name] = plugin_info.version
            cls._plugin_descriptions[plugin_info.name] = plugin_info.description
            return True
        except Exception as e:
            logger.error(f"Failed to add plugin info: {e}")
            return False

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

    def _cleanup_plugin(self, plugin_name: str):
        """Performs cleanup operations for a plugin."""
        ref = self._plugin_instances.get(plugin_name)
        if ref:
            instance = ref()
            if instance and hasattr(instance, "cleanup"):
                try:
                    instance.cleanup()
                except Exception as e:
                    logger.error(f"Error cleaning up plugin '{plugin_name}': {e}")

            try:
                self._plugin_instances.pop(plugin_name, None)
                self._loaded_plugins.discard(plugin_name)
            except Exception as e:
                logger.error(f"Error cleaning up plugin '{plugin_name}': {e}")

    def _register_plugin(self, plugin_name: str, bot: Optional[TeleBot] = None):
        """Registers a single plugin with enhanced security and resource management."""
        logger.debug(f"Attempting to register plugin: '{plugin_name}'")

        if not self._validate_plugin_name(plugin_name):
            logger.error(f"Invalid plugin name: '{plugin_name}'. Skipping.")
            return

        if not self._module_exists(plugin_name):
            logger.error(f"Plugin '{plugin_name}' not found. Skipping.")
            return

        try:
            # Prepare all necessary data before acquiring the lock
            module = self._import_module(plugin_name)
            config = self._import_module_config(plugin_name)

            plugin_info = self._extract_plugin_info(config)
            if not plugin_info:
                logger.error(f"Invalid plugin configuration for '{plugin_name}'.")
                return

            permissions = self._extract_plugin_permissions(config)
            plugin_classes = self._find_plugin_classes(module)

            if not plugin_classes:
                logger.error(f"No valid plugin class found in '{plugin_name}'.")
                return

            # Create plugin instance
            plugin_instance = plugin_classes[0](bot)

            # Clean up existing plugin
            self._cleanup_plugin(plugin_name)

            try:
                if not self.add_plugin_info(plugin_info):
                    return

                self._plugin_instances[plugin_name] = weakref.ref(plugin_instance)

                if permissions.base_permission:
                    plugin_instance.register()
                    self._loaded_plugins.add(plugin_name)
                    logger.info(
                        f"Plugin '{plugin_info.name}' (v{plugin_info.version}) registered successfully."
                    )
                else:
                    logger.warning(
                        f"Plugin '{plugin_info.name}' does not have permission to execute commands. Skipping registration."
                    )

            except Exception as error:
                logger.exception(
                    f"Unexpected error registering plugin '{plugin_name}': {error}"
                )
                self._cleanup_plugin(plugin_name)

        except Exception as error:
            logger.exception(
                f"Unexpected error registering plugin '{plugin_name}': {error}"
            )
            self._cleanup_plugin(plugin_name)

    def register_plugins(self, plugin_names: List[str], bot: Optional[TeleBot] = None):
        """Registers multiple plugins with enhanced error handling."""
        plugins_to_register = [
            name.strip()
            for plugin in plugin_names
            for name in plugin.split(",")
            if name.strip() and self._validate_plugin_name(name.strip())
        ]

        for plugin_name in plugins_to_register:
            self._register_plugin(plugin_name, bot)

    @classmethod
    def is_plugin_loaded(cls, plugin_name: str) -> bool:
        return plugin_name in cls._loaded_plugins

    def cleanup_all_plugins(self):
        """Cleanly shuts down all registered plugins."""

        try:
            for plugin_name in list(self._loaded_plugins):
                self._cleanup_plugin(plugin_name)
            self._loaded_plugins.clear()
        except Exception as e:
            logger.error(f"Error cleaning up plugins: {e}")

    def __del__(self):
        """Ensure cleanup when the manager is destroyed."""
        self.cleanup_all_plugins()
