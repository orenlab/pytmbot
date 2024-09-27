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

from pytmbot.plugins.monitor.models import MonitoringData
from pytmbot.utils.utilities import is_running_in_docker

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
        self.is_running_in_docker: bool = is_running_in_docker()

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
        Checks the current disk usage for all physical partitions and sends a notification if any partition's usage exceeds the configured threshold.
        Excludes partitions where device names or file system types match certain system partitions when running locally.
        """
        excluded_keywords = ["loop", "tmpfs", "devtmpfs", "proc", "sysfs", "cgroup", "mqueue", "hugetlbfs", "overlay",
                             "aufs"]
        threshold = self.settings.plugins_config.monitor.tracehold.disk_usage_threshold[0]

        try:
            partitions = psutil.disk_partitions()
        except psutil.Error as e:
            self.bot_logger.error(f"Error retrieving disk partitions: {e}")
            return 0.0

        def calculate_avg_disk_usage(_partitions):
            total_usage = 0.0
            count = 0
            for partition in _partitions:
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                except psutil.Error as err:
                    self.bot_logger.error(f"Error checking disk usage for {partition.device}: {err}")
                    continue

                if usage.percent > threshold:
                    self._send_notification(
                        f"{self.config.emoji_for_notification} Disk usage is high on {partition.device}: {usage.percent}%")
                total_usage += usage.percent
                count += 1

            return total_usage / count if count > 0 else 0.0

        match self.is_running_in_docker:
            case True:
                return calculate_avg_disk_usage(partitions)
            case False:
                filtered_partitions = [
                    p for p in partitions if
                    all(excl not in p.device and excl not in p.fstype for excl in excluded_keywords)
                ]
                return calculate_avg_disk_usage(filtered_partitions)

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
        periods_in_days = range(1, 8)

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
