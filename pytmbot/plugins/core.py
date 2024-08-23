import importlib

from pytmbot.globals import settings, var_config
from pytmbot.logs import bot_logger


class PluginCore:
    def __init__(self, bot):
        self.bot = bot
        self.settings = settings
        self.var_config = var_config
        self.bot_logger = bot_logger
        self.plugins = {}

    def register_plugin(self, plugin_name):
        try:
            plugin_module = importlib.import_module(f"plugins.{plugin_name}")
            plugin_class = getattr(plugin_module, plugin_name)
            plugin_instance = plugin_class(self.bot)
            self.plugins[plugin_name] = plugin_instance
            bot_logger.info(f"Plugin {plugin_name} registered")
        except ImportError:
            bot_logger.error(f"Plugin {plugin_name} not found")

    @staticmethod
    def __get_plugin_config(plugin_name):
        try:
            with open(f"plugins/{plugin_name}/config.yaml") as f:
                plugin_config = f.read()
            return plugin_config
        except FileNotFoundError:
            return None
