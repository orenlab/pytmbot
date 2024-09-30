from telebot import TeleBot
from telebot.types import Message

from pytmbot.globals import keyboards, em
from pytmbot.parsers.compiler import Compiler
from pytmbot.plugins.monitor import config
from pytmbot.plugins.monitor.config import load_config
from pytmbot.plugins.monitor.methods import SystemMonitorPlugin, MonitoringGraph
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
        monitoring_graph (MonitoringGraph): An instance of MonitoringGraph for graphing system metrics.
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
        self.monitoring_graph = MonitoringGraph()

    def handle_monitoring(self, message: Message) -> Message:
        available_periods = self.monitoring_graph.get_time_periods()
        if not available_periods:
            keyboard = keyboards.build_reply_keyboard(keyboard_type="back_keyboard")
        else:
            keyboard = keyboards.build_reply_keyboard(
                plugin_keyboard_data=config.KEYBOARD
            )
        emojis = {
            "minus": em.get_emoji("minus"),
            "thought_balloon": em.get_emoji("thought_balloon"),
            "warning": em.get_emoji("warning"),
        }
        with Compiler(
            template_name="plugin_monitor_index.jinja2",
            first_name=message.from_user.first_name,
            available_periods=available_periods,
            **emojis,
        ) as compiler:
            response = compiler.compile()
        return self.bot.send_message(
            message.chat.id, text=response, reply_markup=keyboard, parse_mode="Markdown"
        )

    def handle_cpu_usage(self, message: Message) -> Message:
        """
        Handles 'CPU usage' messages by sending a graph of the last hour's CPU usage.

        :param message: The incoming Message object from Telegram.
        :return: A Message object with a graph of the last hour's CPU usage.
        """
        try:
            graph = self.monitoring_graph.plot_data(
                data_type="cpu_usage", period="1 hour(s)"
            )
            if graph is None:
                return self.bot.send_message(message.chat.id, "No data available.")

            return self.bot.send_photo(message.chat.id, graph)
        except Exception as error:
            self.plugin_logger.error(f"Unexpected error occurred: {error}")
            return self.bot.send_message(message.chat.id, "Unexpected error occurred")

    def register(self):
        """
        Registers the SystemMonitorPlugin and starts monitoring.

        This method initializes the SystemMonitorPlugin with the loaded configuration
        and the bot instance, then starts monitoring system metrics.
        """
        monitor_plugin = SystemMonitorPlugin(config=self.config, bot=self.bot)
        monitor_plugin.start_monitoring()
        self.bot.register_message_handler(
            self.handle_monitoring, regexp="Monitoring", pass_bot=True
        )
        self.bot.register_message_handler(self.handle_cpu_usage, regexp="CPU usage")


__all__ = ["MonitoringPlugin"]
