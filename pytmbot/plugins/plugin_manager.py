import importlib
import importlib.util
import inspect
import re
import weakref
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import List, Type, Optional, Dict, Set

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
                'max_memory_mb': 100,
                'max_cpu_percent': 50,
                'execution_timeout_sec': 30
            }


class PluginManager:
    """
    Manages the discovery, validation, and registration of plugins in the pyTMBot system.

    This singleton class handles the loading and registration of plugins, validates plugin names,
    and manages metadata about registered plugins.
    """

    _lock = Lock()
    _instance = None
    _index_keys: Dict[str, str] = {}
    _plugin_names: Dict[str, str] = {}
    _plugin_descriptions: Dict[str, str] = {}
    _plugin_instances: Dict[str, weakref.ref] = {}
    _loaded_plugins: Set[str] = set()

    # Resource monitoring
    _plugin_resources = {
        'default_limits': {
            'max_memory_mb': 100,
            'max_cpu_percent': 50,
            'execution_timeout_sec': 30
        }
    }

    def __new__(cls, *args, **kwargs) -> "PluginManager":
        """
        Creates or retrieves the singleton instance of the PluginManager using double-checked locking.
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super(PluginManager, cls).__new__(cls)
                    cls._instance._initialize()
        return cls._instance

    def _initialize(self):
        """Initialize the plugin manager instance with required attributes."""
        self._plugin_base_path = Path("pytmbot/plugins")
        self._plugin_base_for_import = "pytmbot.plugins"
        self._load_blacklist()

    def _load_blacklist(self):
        """Load blacklisted plugin patterns and names."""
        self._plugin_blacklist = {
            'patterns': [
                r'.*\/.*',  # Prevent directory traversal
                r'^\..*',  # Prevent hidden files
                r'.*\.py$'  # Prevent direct Python file loading
            ],
            'names': {'__pycache__', 'tests', 'examples'}
        }

    @staticmethod
    @lru_cache(maxsize=128)
    def _validate_plugin_name(plugin_name: str) -> bool:
        """
        Validates the plugin name against security patterns and blacklist.

        Args:
            plugin_name (str): The name of the plugin to validate.

        Returns:
            bool: True if the name is valid, False otherwise.
        """
        if not isinstance(plugin_name, str):
            return False

        # Basic pattern validation
        valid_plugin_name_pattern = re.compile(r"^[a-z_]+$")
        if not bool(valid_plugin_name_pattern.match(plugin_name)):
            return False

        # Security checks
        security_patterns = [
            r'\.\.',  # Path traversal
            r'[\/\\]',  # Directory separators
            r'[;&|]',  # Command injection chars
            r'\s',  # Whitespace
        ]

        return not any(re.search(pattern, plugin_name) for pattern in security_patterns)

    def _validate_plugin_path(self, plugin_name: str) -> bool:
        """
        Validates that the plugin path is within the allowed directory.

        Args:
            plugin_name (str): The name of the plugin to validate.

        Returns:
            bool: True if the path is valid, False otherwise.
        """
        try:
            plugin_path = (self._plugin_base_path / plugin_name).resolve()
            base_path = self._plugin_base_path.resolve()
            return base_path in plugin_path.parents
        except (ValueError, RuntimeError):
            return False

    @lru_cache(maxsize=128)
    def _module_exists(self, plugin_name: str) -> bool:
        """
        Checks if the module for the given plugin name exists.

        Args:
            plugin_name (str): The name of the plugin to check.

        Returns:
            bool: True if the module exists, False otherwise.
        """
        module_path = f"{self._plugin_base_for_import}.{plugin_name}.config"
        return importlib.util.find_spec(module_path) is not None

    def _import_module(self, plugin_name: str):
        """
        Safely imports the plugin module with additional security checks.

        Args:
            plugin_name (str): The name of the plugin module to import.

        Returns:
            module: The imported module.

        Raises:
            ImportError: If the module cannot be imported or fails security checks.
        """
        if not self._validate_plugin_path(plugin_name):
            raise ImportError(f"Plugin path validation failed for '{plugin_name}'")

        module_path = f"{self._plugin_base_for_import}.{plugin_name}.plugin"
        try:
            return importlib.import_module(module_path)
        except ImportError as e:
            bot_logger.error(f"ImportError: {e} - Module path: {module_path}")
            raise

    def _import_module_config(self, plugin_name: str):
        """
        Safely imports the plugin configuration module.

        Args:
            plugin_name (str): The name of the plugin configuration module to import.

        Returns:
            module: The imported configuration module.

        Raises:
            ImportError: If the configuration module cannot be imported.
        """
        if not self._validate_plugin_path(plugin_name):
            raise ImportError(f"Plugin config path validation failed for '{plugin_name}'")

        module_path = f"{self._plugin_base_for_import}.{plugin_name}.config"
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
        Extracts and validates the permission settings for the plugin.

        Args:
            module: The plugin configuration module to extract permissions from.

        Returns:
            PluginsPermissionsModel: A permission model object for the plugin.

        Raises:
            ValueError: If permissions are invalid or missing.
        """
        permissions = getattr(module, "PLUGIN_PERMISSIONS", None)

        if not isinstance(permissions, PluginsPermissionsModel):
            bot_logger.error(f"Invalid permissions model in plugin '{module.__name__}'")
            raise ValueError(f"Invalid permissions model for plugin '{module.__name__}'")

        # Validate permission structure
        if not hasattr(permissions, 'base_permission'):
            raise ValueError("Missing base_permission in plugin permissions")

        return permissions

    def _extract_plugin_info(self, module) -> Optional[_PluginInfo]:
        """
        Extracts and validates plugin configuration details.

        Args:
            module: The plugin module from which to extract configuration details.

        Returns:
            Optional[_PluginInfo]: A dataclass containing the plugin's configuration if valid, None otherwise.
        """
        try:
            required_attrs = ['PLUGIN_NAME', 'PLUGIN_VERSION', 'PLUGIN_DESCRIPTION']
            for attr in required_attrs:
                if not hasattr(module, attr):
                    raise AttributeError(f"Missing required attribute: {attr}")

            name = getattr(module, "PLUGIN_NAME")
            version = getattr(module, "PLUGIN_VERSION")
            description = getattr(module, "PLUGIN_DESCRIPTION")
            commands = getattr(module, "PLUGIN_COMMANDS", None)
            index_key = getattr(module, "PLUGIN_INDEX_KEY", None)

            # Extract resource limits if defined
            resource_limits = getattr(module, "PLUGIN_RESOURCE_LIMITS",
                                      self._plugin_resources['default_limits'].copy())

            permissions = self._extract_plugin_permissions(module)

            # Check for host machine requirement
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
                resource_limits=resource_limits
            )
        except AttributeError as e:
            bot_logger.error(f"Plugin config error: missing required attributes - {e}")
            return None

    @classmethod
    def add_plugin_info(cls, plugin_info: _PluginInfo):
        """
        Safely adds information about a plugin to the internal management structures.

        Args:
            plugin_info (_PluginInfo): The information about the plugin to add.
        """
        with cls._lock:
            if plugin_info:
                if plugin_info.index_key:
                    cls._index_keys.update(plugin_info.index_key)
                cls._plugin_names[plugin_info.name] = plugin_info.version
                cls._plugin_descriptions[plugin_info.name] = plugin_info.description

    def _cleanup_plugin(self, plugin_name: str):
        """
        Performs cleanup operations for a plugin.

        Args:
            plugin_name (str): The name of the plugin to clean up.
        """
        with self._lock:
            if plugin_name in self._plugin_instances:
                ref = self._plugin_instances[plugin_name]
                instance = ref()
                if instance and hasattr(instance, 'cleanup'):
                    try:
                        instance.cleanup()
                    except Exception as e:
                        bot_logger.error(f"Error cleaning up plugin '{plugin_name}': {e}")
                del self._plugin_instances[plugin_name]

    def _register_plugin(self, plugin_name: str, bot: Optional[TeleBot] = None):
        """
        Registers a single plugin with enhanced security and resource management.

        Args:
            plugin_name (str): The name of the plugin to register.
            bot (Optional[TeleBot]): The bot instance to which the plugin will be registered.
        """
        bot_logger.debug(f"Attempting to register plugin: '{plugin_name}'")

        if not self._validate_plugin_name(plugin_name):
            bot_logger.error(f"Invalid plugin name: '{plugin_name}'. Skipping.")
            return

        if not self._module_exists(plugin_name):
            bot_logger.error(f"Plugin '{plugin_name}' not found. Skipping.")
            return

        try:
            # Clean up existing instance if present
            self._cleanup_plugin(plugin_name)

            module = self._import_module(plugin_name)
            config = self._import_module_config(plugin_name)

            plugin_info = self._extract_plugin_info(config)
            if not plugin_info:
                bot_logger.error(f"Invalid plugin configuration for '{plugin_name}'.")
                return

            permissions = self._extract_plugin_permissions(config)

            with self._lock:
                self.add_plugin_info(plugin_info)

                plugin_classes = self._find_plugin_classes(module)
                if not plugin_classes:
                    bot_logger.error(f"No valid plugin class found in '{plugin_name}'.")
                    return

                plugin_instance = plugin_classes[0](bot)

                # Store weak reference to plugin instance
                self._plugin_instances[plugin_name] = weakref.ref(plugin_instance)

                # Register if permissions allow
                if permissions.base_permission:
                    plugin_instance.register()
                    self._loaded_plugins.add(plugin_name)

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
            # Ensure cleanup on failure
            self._cleanup_plugin(plugin_name)

    def register_plugins(self, plugin_names: List[str], bot: Optional[TeleBot] = None):
        """
        Registers multiple plugins with enhanced error handling and logging.

        Args:
            plugin_names (List[str]): A list of plugin names to register.
            bot (Optional[TeleBot]): The bot instance to which the plugins will be registered.
        """
        plugins_to_register = [
            name.strip() for plugin in plugin_names for name in plugin.split(",")
            if name.strip() and self._validate_plugin_name(name.strip())
        ]

        for plugin_name in plugins_to_register:
            self._register_plugin(plugin_name, bot)

    def cleanup_all_plugins(self):
        """Cleanly shuts down all registered plugins."""
        with self._lock:
            for plugin_name in list(self._loaded_plugins):
                self._cleanup_plugin(plugin_name)
            self._loaded_plugins.clear()

    def __del__(self):
        """Ensure cleanup when the manager is destroyed."""
        self.cleanup_all_plugins()
