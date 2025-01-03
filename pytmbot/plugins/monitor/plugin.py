from logging import Logger
from typing import Optional, Dict

from telebot import TeleBot
from telebot.types import Message, ReplyKeyboardMarkup

from pytmbot.globals import keyboards, em
from pytmbot.parsers.compiler import Compiler
from pytmbot.plugins.monitor import config
from pytmbot.plugins.monitor.config import load_config
from pytmbot.plugins.monitor.methods import SystemMonitorPlugin
from pytmbot.plugins.monitor.models import MonitorPluginConfig
from pytmbot.plugins.plugin_interface import PluginInterface
from pytmbot.plugins.plugins_core import PluginCore


class MonitoringPlugin(PluginInterface):
    """
    A plugin for monitoring system metrics and interacting with the Telegram bot.

    This plugin initializes the system monitoring plugin and registers it
    with the bot to start monitoring CPU, memory, and disk usage.

    Attributes:
        bot (TeleBot): An instance of TeleBot to interact with Telegram API.
        plugin_logger (Logger): Logger for plugin activities.
        config (Dict[str, Any]): Configuration settings for monitoring.
    """

    __slots__ = ('plugin_logger', 'config')

    def __init__(self, bot: TeleBot) -> None:
        """Initialize MonitoringPlugin with bot instance."""
        super().__init__(bot)
        self.plugin_logger: Logger = PluginCore().logger
        self.config: MonitorPluginConfig = load_config()

    @staticmethod
    def _get_keyboard(available_periods: Optional[list] = None) -> ReplyKeyboardMarkup:
        """Generate appropriate keyboard based on available periods."""
        return (
            keyboards.build_reply_keyboard(keyboard_type="back_keyboard")
            if not available_periods
            else keyboards.build_reply_keyboard(plugin_keyboard_data=config.KEYBOARD)
        )

    def handle_monitoring(self, message: Message) -> Message:
        """Handle monitoring command and return formatted response."""
        available_periods = None  # TODO: Implement period fetching
        keyboard = self._get_keyboard(available_periods)

        emojis = {
            "minus": em.get_emoji("minus"),
            "thought_balloon": em.get_emoji("thought_balloon"),
            "warning": em.get_emoji("warning"),
        }

        with Compiler(
                template_name="plugin_monitor_index.jinja2",
                first_name=message.from_user.first_name,
                available_periods=available_periods,
                **emojis
        ) as compiler:
            response = compiler.compile()

        return self.bot.send_message(
            message.chat.id,
            text=response,
            reply_markup=keyboard,
            parse_mode="Markdown"
        )

    def handle_cpu_usage(self, message: Message) -> Message:
        """Handle CPU usage request."""
        raise NotImplementedError("CPU usage handling not implemented")

    def register(self) -> None:
        """Register SystemMonitorPlugin and start monitoring."""
        try:
            monitor_plugin = SystemMonitorPlugin(config=self.config, bot=self.bot)
            monitor_plugin.start_monitoring()

            self.bot.register_message_handler(
                self.handle_monitoring,
                regexp="Monitoring",
                pass_bot=True
            )
            self.bot.register_message_handler(
                self.handle_cpu_usage,
                regexp="CPU usage"
            )
        except Exception as e:
            self.plugin_logger.error(f"Failed to register monitoring plugin: {str(e)}")
            raise


__all__ = ["MonitoringPlugin"]
