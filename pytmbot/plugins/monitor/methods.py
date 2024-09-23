#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>

Monitor plugin for pyTMBot

pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import importlib.util
import threading
import time

from telebot import TeleBot

# Check if the psutil module is installed
if importlib.util.find_spec("psutil") is None:
    raise ModuleNotFoundError("psutil library is not installed. Please install it.")

from pytmbot.models.settings_model import MonitorConfig
from pytmbot.plugins.plugins_core import PluginCore
import psutil


class SystemMonitorPlugin(PluginCore):
    """
    A plugin for monitoring system resources such as CPU, memory, disk usage, and temperatures.
    Sends notifications to a Telegram bot if any of the monitored resources exceed specified thresholds.
    """

    def __init__(self, config: 'MonitorConfig', bot: TeleBot) -> None:
        """
        Initializes the SystemMonitorPlugin with the given configuration and bot instance.

        Args:
            config (MonitorConfig): Configuration object containing thresholds and other settings.
            bot (TeleBot): Instance of the Telegram bot.
        """
        super().__init__()
        self.bot: TeleBot = bot
        self.monitoring: bool = False
        self.config: 'MonitorConfig' = config
        self.monitor_settings = self.settings.plugins_config.monitor
        self.notification_count: int = 0
        self.max_notifications: int = self.monitor_settings.max_notifications[0]
        self.cpu_temperature_threshold: float = self.monitor_settings.tracehold.cpu_temperature_threshold[0]
        self.gpu_temperature_threshold: float = self.monitor_settings.tracehold.gpu_temperature_threshold[0]
        self.disk_temperature_threshold: float = self.monitor_settings.tracehold.disk_temperature_threshold[0]
        self.monitoring_thread: threading.Thread | None = None
        self.retry_attempts: int = self.monitor_settings.retry_attempts[0]
        self.retry_interval: int = self.monitor_settings.retry_interval[0]
        self.sensors_available: bool = True

        self.bot_logger.debug(f"Monitor plugin initialized with next tracehold settings:"
                              f" max_notifications={self.max_notifications},"
                              f" cpu_temperature_threshold={self.cpu_temperature_threshold},"
                              f" gpu_temperature_threshold={self.gpu_temperature_threshold},"
                              f" disk_temperature_threshold={self.disk_temperature_threshold},"
                              )

    def start_monitoring(self) -> None:
        """
        Starts the system monitoring process in a separate thread.
        If the monitoring fails to start, it will retry up to `retry_attempts` times.
        """
        if not self.monitoring:
            self.bot_logger.info("Attempting to start system monitoring.")
            for attempt in range(self.retry_attempts):
                try:
                    self.monitoring = True
                    self.monitoring_thread = threading.Thread(
                        target=self._monitor_system, daemon=True
                    )
                    self.monitoring_thread.start()
                    self.bot_logger.info("System monitoring started successfully.")
                    return
                except Exception as e:
                    self.bot_logger.error(f"Failed to start monitoring on attempt {attempt + 1}: {e}")
                    self.monitoring = False
                    time.sleep(self.retry_interval)

            self.bot_logger.error("Failed to start system monitoring after multiple attempts. Manual restart required.")
        else:
            self.bot_logger.warning("Monitoring is already running.")

    def stop_monitoring(self) -> None:
        """
        Stops the system monitoring process and waits for the monitoring thread to terminate.
        """
        if self.monitoring:
            self.monitoring = False
            if self.monitoring_thread:
                self.monitoring_thread.join()
            self.bot_logger.info("System monitoring stopped.")
        else:
            self.bot_logger.warning("Monitoring is not running.")

    def _monitor_system(self) -> None:
        """
        Continuously monitors the system resources (CPU, memory, disk usage, and temperatures)
        and sends notifications if any resource exceeds the configured thresholds.
        """
        try:
            while self.monitoring:
                self._check_cpu_usage()
                self._check_memory_usage()
                self._check_disk_usage()
                self._check_temperatures()  # New function to monitor temperatures
                time.sleep(self.settings.plugins_config.monitor.check_interval[0])
        except Exception as e:
            self.bot_logger.error(f"Unexpected error during system monitoring: {e}")
            self.monitoring = False

    def _check_temperatures(self) -> None:
        """
        Checks the current temperatures of system components and sends a notification
        if any component exceeds the configured temperature threshold for that type.
        """
        try:
            temps = psutil.sensors_temperatures()
            if not temps and self.sensors_available:
                self.sensors_available = False
                self.bot_logger.warning("No temperature sensors available on this system.")
                return

            for name, entries in temps.items():
                for entry in entries:
                    match name:
                        case 'coretemp':  # Likely a CPU sensor
                            if entry.current > self.cpu_temperature_threshold:
                                self._send_notification(
                                    f"{self.config.emoji_for_notification}CPU temperature is high: {entry.current}°C (Threshold: {self.cpu_temperature_threshold}°C)"
                                )
                        case 'nvme' | 'disk':  # Disk sensors (e.g., NVMe, HDD)
                            if entry.current > self.disk_temperature_threshold:
                                self._send_notification(
                                    f"{self.config.emoji_for_notification}Disk temperature is high: {entry.current}°C (Threshold: {self.disk_temperature_threshold}°C)"
                                )
                        case 'gpu':  # GPU sensor
                            if entry.current > self.gpu_temperature_threshold:
                                self._send_notification(
                                    f"{self.config.emoji_for_notification}GPU temperature is high: {entry.current}°C (Threshold: {self.gpu_temperature_threshold}°C)"
                                )
                        case _:
                            self.bot_logger.warning(f"Unknown temperature sensor: {name}")
        except psutil.Error as e:
            self.bot_logger.error(f"Error checking temperatures: {e}")
        except ExceptionGroup as eg:
            self.bot_logger.error(f"Multiple errors occurred while checking temperatures: {eg}")

    def _check_cpu_usage(self) -> None:
        """
        Checks the current CPU usage and sends a notification if it exceeds the configured threshold.
        """
        try:
            cpu_usage = psutil.cpu_percent(interval=1)
            if cpu_usage > self.settings.plugins_config.monitor.tracehold.cpu_usage_threshold[0]:
                self._send_notification(f"{self.config.emoji_for_notification}CPU usage is high: {cpu_usage}%")
        except psutil.Error as e:
            self.bot_logger.error(f"Error checking CPU usage: {e}")

    def _check_memory_usage(self) -> None:
        """
        Checks the current memory usage and sends a notification if it exceeds the configured threshold.
        """
        try:
            memory = psutil.virtual_memory()
            if memory.percent > self.settings.plugins_config.monitor.tracehold.memory_usage_threshold[0]:
                self._send_notification(f"{self.config.emoji_for_notification}Memory usage is high: {memory.percent}%")
        except psutil.Error as e:
            self.bot_logger.error(f"Error checking memory usage: {e}")

    def _check_disk_usage(self) -> None:
        """
        Checks the current disk usage for all partitions and sends a notification if any partition's usage exceeds the configured threshold.
        """
        try:
            for partition in psutil.disk_partitions():
                usage = psutil.disk_usage(partition.mountpoint)
                if usage.percent > self.settings.plugins_config.monitor.tracehold.disk_usage_threshold[0]:
                    self._send_notification(
                        f"{self.config.emoji_for_notification}Disk usage is high on {partition.device}: {usage.percent}%")
        except psutil.Error as e:
            self.bot_logger.error(f"Error checking disk usage: {e}")

    def _send_notification(self, message: str) -> None:
        """
        Sends a notification message to the Telegram bot chat.
        If the maximum number of notifications has been reached, no further notifications will be sent.
        """
        if self.notification_count < self.max_notifications:
            try:
                self.notification_count += 1
                sanitized_message = message.replace(self.config.emoji_for_notification, "")
                self.bot_logger.info(f"Sending notification: {sanitized_message}")
                self.bot.send_message(self.settings.chat_id.global_chat_id[0], message)

                # Reset the notification count after 5 minutes (300 seconds)
                threading.Timer(300, self._reset_notification_count).start()

            except Exception as e:
                self.bot_logger.error(f"Failed to send notification: {e}")
        else:
            self.bot_logger.warning("Max notifications reached; no more notifications will be sent.")

    def _reset_notification_count(self) -> None:
        """
        Resets the notification count to 0 after a specified delay.
        """
        self.notification_count = 0
        self.bot_logger.info("Notification count has been reset.")
