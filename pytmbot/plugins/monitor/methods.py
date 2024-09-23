#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>

Monitor plugin for pyTMBot

pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import importlib.util

import pygal
from telebot import TeleBot

# Check if the psutil module is installed
if importlib.util.find_spec("psutil") is None:
    raise ModuleNotFoundError("psutil library is not installed. Please install it.")

from pytmbot.models.settings_model import MonitorConfig
from pytmbot.plugins.plugins_core import PluginCore
from pytmbot.logs import bot_logger
import psutil

from collections import deque
from datetime import datetime
import threading
import time
from datetime import timedelta
from io import BytesIO


class MonitoringData:
    """Singleton class for storing and managing monitoring data."""

    _instance = None

    def __new__(cls, *args, **kwargs):
        """Override __new__ to ensure only one instance is created."""
        if cls._instance is None:
            cls._instance = super(MonitoringData, cls).__new__(cls)
            bot_logger.debug("MonitoringData singleton instance created.")
        return cls._instance

    def __init__(self, retention_days: int = 7):
        """Initialize the class with a retention period."""
        # To ensure __init__ is not called multiple times in case of repeated instantiation
        if not hasattr(self, 'initialized'):  # This is to ensure it's only initialized once
            self.retention_days = retention_days
            self.data = {
                "cpu_usage": deque(),
                "memory_usage": deque(),
                "disk_usage": deque(),
                "temperatures": deque(),
            }
            self.stop_event = threading.Event()
            self.cleaning_thread = threading.Thread(target=self._clean_old_data, daemon=True)
            self.cleaning_thread.start()
            self.initialized = True  # Mark as initialized to avoid multiple initializations
            bot_logger.info(f"MonitoringData initialized with retention period of {self.retention_days} days.")

    def add_data(self, cpu: float, memory: float, disk: float, temperature: float):
        """Adds new data to the storage."""
        timestamp = datetime.now()
        self.data["cpu_usage"].append((timestamp, cpu))
        self.data["memory_usage"].append((timestamp, memory))
        self.data["disk_usage"].append((timestamp, disk))
        self.data["temperatures"].append((timestamp, temperature))

    def _clean_old_data(self):
        """Removes data older than the retention period."""
        while not self.stop_event.is_set():
            self._remove_old_entries()
            time.sleep(3600)  # Check every hour

    def _remove_old_entries(self):
        """Removes old entries from the data."""
        cutoff_time = datetime.now() - timedelta(days=self.retention_days)
        for key in self.data.keys():
            old_count = len(self.data[key])
            while self.data[key] and self.data[key][0][0] < cutoff_time:
                self.data[key].popleft()
            if old_count != len(self.data[key]):
                bot_logger.debug(f"Removed old entries from {key}, new count: {len(self.data[key])}.")

    def stop_cleaning(self):
        """Stops the background cleaning thread."""
        self.stop_event.set()
        self.cleaning_thread.join()
        bot_logger.debug("Stopped the cleaning thread for MonitoringData.")

    def get_data(self):
        """Returns the stored data."""
        bot_logger.debug("Data retrieved from MonitoringData.")
        return {key: list(value) for key, value in self.data.items()}


class SystemMonitorPlugin(PluginCore):
    """
    A plugin for monitoring system resources such as CPU, memory, disk usage, and temperatures.
    Sends notifications to a Telegram bot if any of the monitored resources exceed specified thresholds.
    """

    def __init__(self, config: 'MonitorConfig', bot: TeleBot) -> None:
        super().__init__()
        self.bot: TeleBot = bot
        self.monitoring: bool = False
        self.config: 'MonitorConfig' = config
        self.monitor_settings = self.settings.plugins_config.monitor
        self.notification_count: int = 0
        self.max_notifications: int = self.monitor_settings.max_notifications[0]
        self.cpu_temperature_threshold: float = self.monitor_settings.tracehold.cpu_temperature_threshold[0]
        self.pch_temperature_threshold = self.cpu_temperature_threshold
        self.gpu_temperature_threshold: float = self.monitor_settings.tracehold.gpu_temperature_threshold[0]
        self.disk_temperature_threshold: float = self.monitor_settings.tracehold.disk_temperature_threshold[0]
        self.monitoring_thread: threading.Thread | None = None
        self.retry_attempts: int = self.monitor_settings.retry_attempts[0]
        self.retry_interval: int = self.monitor_settings.retry_interval[0]
        self.check_interval: int = self.monitor_settings.check_interval[0]  # Initial check interval
        self.load_threshold: float = 70.0  # Threshold for load-based interval adjustment
        self.sensors_available: bool = True
        self.cpu_usage_is_high: bool = False

        # New monitoring data instance
        self.monitoring_data = MonitoringData(retention_days=7)

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
            self.monitoring_data.stop_cleaning()
            self.bot_logger.info("System monitoring stopped.")
        else:
            self.bot_logger.warning("Monitoring is not running.")

    def _monitor_system(self) -> None:
        try:
            while self.monitoring:
                self._adjust_check_interval()
                cpu_usage = self._check_cpu_usage()
                memory_usage = self._check_memory_usage()
                disk_usage = self._check_disk_usage()
                temperatures = self._check_temperatures()

                self.monitoring_data.add_data(cpu_usage, memory_usage, disk_usage, temperatures)

                time.sleep(self.check_interval)
        except Exception as e:
            self.bot_logger.error(f"Unexpected error during system monitoring: {e}")
            self.monitoring = False

    def _adjust_check_interval(self) -> None:
        """
        Adjust the check interval based on current CPU load.
        """
        cpu_load = psutil.cpu_percent(interval=1)
        if cpu_load > self.load_threshold:
            self.cpu_usage_is_high = True
            self.check_interval = 10  # Increase interval if load is high
            self.bot_logger.info(
                f"High CPU load detected ({cpu_load}%). Increasing check interval to {self.check_interval} seconds.")
        else:
            self.check_interval = self.monitor_settings.check_interval[0]  # Restore to normal interval
            if self.cpu_usage_is_high:
                self.cpu_usage_is_high = False
                self.bot_logger.debug(
                    f"CPU load is normal ({cpu_load}%). Restoring check interval to {self.check_interval} seconds.")

    def _check_temperatures(self) -> float:
        """Checks the current temperatures of system components and sends notifications if thresholds are exceeded."""
        current_temp = 0.0
        try:
            temps = psutil.sensors_temperatures()
            if not temps and self.sensors_available:
                self.sensors_available = False
                self.bot_logger.warning("No temperature sensors available on this system.")
                return current_temp

            for name, entries in temps.items():
                for entry in entries:
                    match name:
                        case 'coretemp':
                            if entry.current > self.cpu_temperature_threshold:
                                self._send_notification(
                                    f"{self.config.emoji_for_notification}CPU temperature is high: {entry.current}°C (Threshold: {self.cpu_temperature_threshold}°C)"
                                )
                        case 'nvme' | 'disk':
                            if entry.current > self.disk_temperature_threshold:
                                self._send_notification(
                                    f"{self.config.emoji_for_notification}Disk temperature is high: {entry.current}°C (Threshold: {self.disk_temperature_threshold}°C)"
                                )
                        case 'gpu':
                            if entry.current > self.gpu_temperature_threshold:
                                self._send_notification(
                                    f"{self.config.emoji_for_notification}GPU temperature is high: {entry.current}°C (Threshold: {self.gpu_temperature_threshold}°C)"
                                )
                        case _ if 'pch' in name.lower():
                            if entry.current > self.pch_temperature_threshold:
                                self._send_notification(
                                    f"{self.config.emoji_for_notification}PCH temperature is high: {entry.current}°C (Threshold: {self.pch_temperature_threshold}°C)"
                                )
                        case _:
                            self.bot_logger.warning(f"Unknown temperature sensor: {name}")
                    current_temp = entry.current
        except psutil.Error as e:
            self.bot_logger.error(f"Error checking temperatures: {e}")
        except ExceptionGroup as eg:
            self.bot_logger.error(f"Multiple error occurred while checking temperatures: {eg}")

        return current_temp

    def _check_cpu_usage(self) -> float:
        """
        Checks the current CPU usage and sends a notification if it exceeds the configured threshold.
        """
        try:
            cpu_usage = psutil.cpu_percent(interval=1)
            if cpu_usage > self.settings.plugins_config.monitor.tracehold.cpu_usage_threshold[0]:
                self._send_notification(f"{self.config.emoji_for_notification}CPU usage is high: {cpu_usage}%")
            return cpu_usage
        except psutil.Error as e:
            self.bot_logger.error(f"Error checking CPU usage: {e}")
            return 0.0

    def _check_memory_usage(self) -> float:
        """
        Checks the current memory usage and sends a notification if it exceeds the configured threshold.
        """
        try:
            memory = psutil.virtual_memory()
            if memory.percent > self.settings.plugins_config.monitor.tracehold.memory_usage_threshold[0]:
                self._send_notification(
                    f"{self.config.emoji_for_notification}Memory usage is high: {memory.percent}%")
            return memory.percent
        except psutil.Error as e:
            self.bot_logger.error(f"Error checking memory usage: {e}")
            return 0.0

    def _check_disk_usage(self) -> float:
        """
        Checks the current disk usage for all partitions and sends a notification if any partition's usage exceeds the configured threshold.
        """
        total_disk_usage = 0.0
        try:
            for partition in psutil.disk_partitions():
                usage = psutil.disk_usage(partition.mountpoint)
                if usage.percent > self.settings.plugins_config.monitor.tracehold.disk_usage_threshold[0]:
                    self._send_notification(
                        f"{self.config.emoji_for_notification}Disk usage is high on {partition.device}: {usage.percent}%")
                total_disk_usage += usage.percent
            return total_disk_usage / len(
                psutil.disk_partitions()) if psutil.disk_partitions() else 0.0
        except psutil.Error as e:
            self.bot_logger.error(f"Error checking disk usage: {e}")
            return 0.0

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


class MonitoringGraph:
    """Class for generating and managing monitoring graphs."""

    def __init__(self):
        self.monitoring_data = MonitoringData()

    def get_time_periods(self):
        """Returns available time periods based on the stored data."""
        now = datetime.now()
        available_periods = []
        data = self.monitoring_data.get_data()["cpu_usage"]

        if not data:
            bot_logger.warning("No data available for any time period.")
            return available_periods

        earliest_timestamp = data[0][0]

        periods_in_hours = [1, 6, 12, 24]
        periods_in_days = range(1, 8)  # 1-7 дней

        for hours in periods_in_hours:
            period_start = now - timedelta(hours=hours)
            if earliest_timestamp <= period_start:
                available_periods.append(f'{hours} hour(s)')
            else:
                break

        for days in periods_in_days:
            period_start = now - timedelta(days=days)
            if earliest_timestamp <= period_start:
                available_periods.append(f'{days} day(s)')
            else:
                break

        bot_logger.info(f"Available time periods for graphs: {available_periods}.")
        return available_periods

    def plot_data(self, data_type: str, period: str):
        """Generates a plot for the specified data type and time period."""
        bot_logger.debug(f"Generating plot for {data_type} over the last {period}.")
        data = self.monitoring_data.get_data()[data_type]

        # Determine if period is in hours or days
        if 'hour' in period:
            hours = int(period.split()[0])
            cutoff_time = datetime.now() - timedelta(hours=hours)
        else:
            days = int(period.split()[0])
            cutoff_time = datetime.now() - timedelta(days=days)

        # Filter data by time period
        filtered_data = [(timestamp, value) for timestamp, value in data if timestamp >= cutoff_time]

        if not filtered_data:
            bot_logger.warning(f"No data available for the specified period: {period}.")
            return None

        timestamps, values = zip(*filtered_data)

        # Create a Pygal line chart
        line_chart = pygal.Line()
        line_chart.title = f'{data_type.replace("_", " ").title()} Over Last {period}'
        line_chart.x_labels = [ts.strftime('%Y-%m-%d %H:%M:%S') for ts in timestamps]
        line_chart.add(data_type.replace("_", " ").title(), values)

        # Save the plot to a BytesIO object
        img_buffer = BytesIO()
        img_buffer.write(line_chart.render(is_unicode=True).encode('utf-8'))
        img_buffer.seek(0)

        bot_logger.info(f"Plot generated for {data_type} over the last {period}.")
        return img_buffer

    def generate_inline_buttons(self):
        """Generates inline buttons for available time periods."""
        periods = self.get_time_periods()
        buttons = [f"{period}" for period in periods]
        bot_logger.debug(f"Generated inline buttons: {buttons}.")
        return buttons
