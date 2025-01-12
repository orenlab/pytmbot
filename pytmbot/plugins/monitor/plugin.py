from telebot import TeleBot
from telebot.types import Message

from pytmbot.globals import keyboards, em
from pytmbot.parsers.compiler import Compiler
from pytmbot.plugins.monitor import config
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

    def handle_monitoring(self, message: Message) -> Message:
        available_periods = None
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
        pass

    def register(self):
        """
        Registers the SystemMonitorPlugin and starts monitoring.

        This method initializes the SystemMonitorPlugin with the loaded configuration
        and the bot instance, then starts monitoring system metrics.
        """
        try:
            monitor_plugin = SystemMonitorPlugin(config=self.config, bot=self.bot)
            monitor_plugin.start_monitoring()
            self.bot.register_message_handler(
                self.handle_monitoring, regexp="Monitoring", pass_bot=True
            )
            self.bot.register_message_handler(self.handle_cpu_usage, regexp="CPU usage")
        except Exception as e:
            self.plugin_logger.error(f"Failed to register monitoring plugin: {e}")


__all__ = ["MonitoringPlugin"]
