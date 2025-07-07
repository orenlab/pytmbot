#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from typing import Optional

from telebot import TeleBot
from telebot.types import Message, ReplyKeyboardMarkup

from pytmbot.globals import keyboards, em
from pytmbot.parsers.compiler import Compiler
from pytmbot.plugins.monitor import config
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
    """

    __slots__ = ("plugin_logger", "config", "__weakref__")

    def __init__(self, bot: TeleBot) -> None:
        """Initialize MonitoringPlugin with bot instance."""
        super().__init__(bot)
        self.plugin_logger = plugin.logger

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
            **emojis,
        ) as compiler:
            response = compiler.compile()

        return self.bot.send_message(
            message.chat.id, text=response, reply_markup=keyboard, parse_mode="Markdown"
        )

    def handle_cpu_usage(self, message: Message) -> Message:
        """Handle CPU usage request."""
        raise NotImplementedError("CPU usage handling not implemented")

    def register(self) -> TeleBot:
        """Register SystemMonitorPlugin and start monitoring."""
        try:
            monitor_plugin = SystemMonitorPlugin(bot=self.bot)
            monitor_plugin.start_monitoring()

            self.bot.register_message_handler(
                self.handle_monitoring, regexp="Monitoring"
            )
            self.bot.register_message_handler(self.handle_cpu_usage, regexp="CPU usage")

            return self.bot

        except Exception as e:
            self.plugin_logger.error(f"Failed to register monitoring plugin: {str(e)}")
            raise


__all__ = ["MonitoringPlugin"]
