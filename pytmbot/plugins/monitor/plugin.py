from telebot import TeleBot

from pytmbot.plugins.monitor.config import load_config
from pytmbot.plugins.monitor.methods import SystemMonitorPlugin
from pytmbot.plugins.plugin_interface import PluginInterface
from pytmbot.plugins.plugins_core import PluginCore

plugin = PluginCore()


class MonitoringPlugin(PluginInterface):
    """
    A plugin for monitoring system metrics and interacting with the Telegram bot.

    This plugin initializes the system monitoring plugin and registers it
    with the bot to start monitoring CPU, memory, and disk usage.

    Attributes:
        bot (TeleBot): An instance of TeleBot to interact with Telegram API.
        plugin_logger: Logger inherited from PluginCore for logging plugin activities.
        config (dict): Configuration settings loaded for the monitoring plugin.
    """

    def __init__(self, bot: TeleBot):
        """
        Initializes the MonitoringPlugin with the given bot instance.

        Args:
            bot (TeleBot): An instance of TeleBot to interact with Telegram API.
        """
        super().__init__(bot)
        self.plugin_logger = plugin.bot_logger
        self.config = load_config()

    def register(self):
        """
        Registers the SystemMonitorPlugin and starts monitoring.

        This method initializes the SystemMonitorPlugin with the loaded configuration
        and the bot instance, then starts monitoring system metrics.
        """
        monitor_plugin = SystemMonitorPlugin(config=self.config, bot=self.bot)
        monitor_plugin.start_monitoring()


__all__ = ["MonitoringPlugin"]
