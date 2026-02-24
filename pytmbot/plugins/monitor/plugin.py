#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from telebot import TeleBot
from telebot.types import Message, ReplyKeyboardMarkup

from pytmbot.adapters.psutil.adapter import PsutilAdapter
from pytmbot.globals import get_emoji_converter, get_keyboards
from pytmbot.parsers.compiler import Compiler
from pytmbot.plugins.monitor import config
from pytmbot.plugins.monitor.methods import SystemMonitorPlugin
from pytmbot.plugins.plugin_interface import PluginInterface
from pytmbot.plugins.plugins_core import PluginCore

plugin = PluginCore()
em = get_emoji_converter()
keyboards = get_keyboards()


class MonitoringPlugin(PluginInterface):
    """
    A plugin for monitoring system metrics and interacting with the Telegram bot.

    This plugin initializes the system monitoring plugin and registers it
    with the bot to start monitoring CPU, memory, and disk usage.

    Attributes:
        bot (TeleBot): An instance of TeleBot to interact with Telegram API.
    """

    __slots__ = ("plugin_logger", "config", "__weakref__")

    def __init__(self, bot: TeleBot) -> None:
        """Initialize MonitoringPlugin with bot instance."""
        super().__init__(bot)
        self.plugin_logger = plugin.logger

    @staticmethod
    def _get_keyboard(available_periods: list | None = None) -> ReplyKeyboardMarkup:
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

        user_name = (
            message.from_user.first_name if message.from_user else None
        ) or "User"
        response = Compiler.quick_render(
            template_name="plugin_monitor_index.jinja2",
            first_name=user_name,
            available_periods=available_periods,
            **emojis,
        )

        return self.bot.send_message(
            message.chat.id, text=response, reply_markup=keyboard, parse_mode="Markdown"
        )

    def handle_cpu_usage(self, message: Message) -> Message:
        """Handle CPU usage request."""
        adapter = PsutilAdapter()

        try:
            cpu_stats = adapter.get_cpu_usage()
            load_avg = adapter.get_load_average()
            top_processes = adapter.get_top_processes(count=5)

            cpu_percent = float(cpu_stats.get("cpu_percent", 0.0))
            cpu_per_core = cpu_stats.get("cpu_percent_per_core", [])

            per_core_preview = ", ".join(
                f"#{index + 1}: {core_value:.1f}%"
                for index, core_value in enumerate(cpu_per_core[:8])
            )
            if len(cpu_per_core) > 8:
                per_core_preview = f"{per_core_preview}, ..."
            if not per_core_preview:
                per_core_preview = "N/A"

            if top_processes:
                top_lines = "\n".join(
                    (
                        f"• {proc['name']} (PID {proc['pid']}): "
                        f"CPU {proc['cpu_percent']:.1f}%, "
                        f"MEM {proc['memory_percent']:.1f}%"
                    )
                    for proc in top_processes
                )
            else:
                top_lines = "• N/A"

            text = "\n".join(
                [
                    f"{em.get_emoji('chart_increasing')} CPU usage snapshot",
                    f"• Overall: {cpu_percent:.1f}%",
                    f"• Cores: {len(cpu_per_core)}",
                    f"• Per-core (first 8): {per_core_preview}",
                    (
                        f"• Load average: "
                        f"{load_avg[0]:.2f} / {load_avg[1]:.2f} / {load_avg[2]:.2f}"
                    ),
                    "",
                    "Top processes:",
                    top_lines,
                ]
            )

            keyboard = keyboards.build_reply_keyboard(
                plugin_keyboard_data=config.KEYBOARD
            )
            return self.bot.send_message(
                message.chat.id, text=text, reply_markup=keyboard
            )

        except Exception as error:
            self.plugin_logger.error(
                "bot.plugins.monitor.plugin.cpu.snapshot.fail", error=str(error)
            )
            return self.bot.send_message(
                message.chat.id,
                "⚠️ Failed to collect CPU usage metrics. Please try again.",
            )
        finally:
            adapter.close()

    def register(self) -> None:
        """Register SystemMonitorPlugin and start monitoring."""
        try:
            monitor_plugin = SystemMonitorPlugin(bot=self.bot)
            monitor_plugin.start_monitoring()

            self.bot.register_message_handler(
                self.handle_monitoring, regexp="Monitoring"
            )
            self.bot.register_message_handler(self.handle_cpu_usage, regexp="CPU usage")

        except Exception:
            self.plugin_logger.error(
                "bot.plugins.monitor.plugin.register.monitoring.fail"
            )
            raise


__all__ = ["MonitoringPlugin"]
