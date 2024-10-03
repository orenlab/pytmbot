#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>

Monitor plugin for pyTMBot

pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import threading
import time
from typing import Optional

import psutil
from telebot import TeleBot

from pytmbot.db.influxdb.influxdb_interface import InfluxDBInterface
from pytmbot.models.settings_model import MonitorConfig
from pytmbot.plugins.plugins_core import PluginCore
from pytmbot.settings import settings
from pytmbot.utils.utilities import is_running_in_docker


class SystemMonitorPlugin(PluginCore):
    """
    A plugin for monitoring system resources such as CPU, memory, disk usage, and temperatures.
    Sends notifications to a Telegram bot if any of the monitored resources exceed specified thresholds.
    """

    def __init__(self, config: "MonitorConfig", bot: TeleBot, event_threshold_duration: int = 60) -> None:
        """
        Initializes the SystemMonitorPlugin with the given bot instance and configuration.

        Args:
            config (MonitorConfig): Configuration for the SystemMonitorPlugin.
            bot (TeleBot): An instance of TeleBot to interact with Telegram API.
            event_threshold_duration (int): Minimum duration (in seconds) that a threshold event must persist
                                             before sending a notification. Defaults to 60 seconds.
        """
        super().__init__()
        self.bot: TeleBot = bot
        self.config: "MonitorConfig" = config
        self.monitoring: bool = False
        self.notification_count: int = 0
        self.monitor_settings = self.settings.plugins_config.monitor
        self.max_notifications: int = self.monitor_settings.max_notifications[0]
        self.retry_attempts: int = self.monitor_settings.retry_attempts[0]
        self.retry_interval: int = self.monitor_settings.retry_interval[0]
        self.check_interval: int = self.monitor_settings.check_interval[0]
        self.event_threshold_duration: int = event_threshold_duration  # Minimum event duration before alert

        # Monitoring thresholds
        self.cpu_temperature_threshold: float = self.monitor_settings.tracehold.cpu_temperature_threshold[0]
        self.pch_temperature_threshold = self.cpu_temperature_threshold
        self.gpu_temperature_threshold: float = self.monitor_settings.tracehold.gpu_temperature_threshold[0]
        self.disk_temperature_threshold: float = self.monitor_settings.tracehold.disk_temperature_threshold[0]
        self.cpu_usage_threshold = self.monitor_settings.tracehold.cpu_usage_threshold[0]
        self.disk_usage_tracehold = self.monitor_settings.tracehold.disk_usage_threshold[0]
        self.load_threshold: float = 70.0  # Threshold for load-based interval adjustment

        # InfluxDB settings
        self._url = settings.influxdb.url[0].get_secret_value()
        self._token = settings.influxdb.token[0].get_secret_value()
        self._org = settings.influxdb.org[0].get_secret_value()
        self._bucket = settings.influxdb.bucket[0].get_secret_value()
        self.influxdb_client = InfluxDBInterface(url=self._url, token=self._token, org=self._org, bucket=self._bucket)

        # Check if Docker is running
        self.is_docker = is_running_in_docker()

        # Check if sensors are available
        self.sensors_available: bool = True

        # Initialize state tracking for event durations
        self.event_start_times = {}
        self.bot_logger.debug("Monitor plugin initialized.")

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
                    monitoring_thread = threading.Thread(
                        target=self._monitor_system, daemon=True
                    )
                    monitoring_thread.start()
                    self.bot_logger.info("System monitoring started successfully.")
                    return
                except Exception as e:
                    self.bot_logger.error(
                        f"Failed to start monitoring on attempt {attempt + 1}: {e}"
                    )
                    time.sleep(self.retry_interval)

            self.bot_logger.error(
                "Failed to start system monitoring after multiple attempts. Manual restart required."
            )
        else:
            self.bot_logger.warning("Monitoring is already running.")

    def stop_monitoring(self) -> None:
        """
        Stops the system monitoring process.
        """
        if self.monitoring:
            self.monitoring = False
            self.bot_logger.info("System monitoring stopped.")
        else:
            self.bot_logger.warning("Monitoring is not running.")

    def _monitor_system(self) -> None:
        event_durations = {
            "disk_usage": {},
            "temperatures": {}
        }

        try:
            while self.monitoring:
                self._adjust_check_interval()
                cpu_usage = self._check_cpu_usage()
                memory_usage = self._check_memory_usage()
                disk_usage = self._check_disk_usage()
                temperatures = self._check_temperatures()

                # Track disk usage events individually for each disk
                for disk, usage in disk_usage.items():
                    disk_event_duration = self._track_event_duration(f"disk_{disk}_usage",
                                                                     usage > self.disk_usage_tracehold)
                    event_durations["disk_usage"][disk] = disk_event_duration

                # Track temperatures individually for each sensor
                for sensor, temp in temperatures.items():
                    temp_event_duration = self._track_event_duration(f"temp_{sensor}",
                                                                     temp > self._get_temp_threshold(sensor))
                    event_durations["temperatures"][sensor] = temp_event_duration

                # Collect only metrics that exceeded thresholds for longer than the minimal interval
                fields = {
                    "cpu_usage": cpu_usage,
                    "memory_usage": memory_usage,
                    **{f"disk_{key}_usage": value for key, value in disk_usage.items()},
                    **{f"temp_{key}": value for key, value in temperatures.items()}
                }

                with self.influxdb_client:
                    self.influxdb_client.write_data("system_metrics", fields)

                # Send notifications if thresholds are exceeded
                self._send_aggregated_notifications(cpu_usage, memory_usage, disk_usage, temperatures, event_durations)

                time.sleep(self.check_interval)
        except Exception as e:
            self.bot_logger.exception(f"Unexpected error during system monitoring: {e}")
            self.monitoring = False

    def _track_event_duration(self, event_name: str, event_occurred: bool) -> Optional[float]:
        """
        Track the start time of an event and return the duration it has been active.
        Also detect when the event has ended to send a notification.

        Args:
            event_name (str): Name of the event being tracked (e.g., "cpu_usage_exceeded").
            event_occurred (bool): Whether the event is currently occurring.

        Returns:
            Optional[float]: The duration (in seconds) the event has been active, or None if the event is not ongoing.
        """
        current_time = time.time()

        if event_occurred:
            if event_name not in self.event_start_times:
                # Start tracking the event
                self.event_start_times[event_name] = current_time
            return current_time - self.event_start_times[event_name]
        else:
            if event_name in self.event_start_times:
                # Event ended, trigger resolution notification
                event_duration = current_time - self.event_start_times[event_name]
                self._send_resolution_notification(event_name, event_duration)
                self.event_start_times.pop(event_name, None)
            return None

    def _send_resolution_notification(self, event_name: str, event_duration: float) -> None:
        """
        Sends a notification when an event (e.g., high CPU usage) has been resolved.

        Args:
            event_name (str): The name of the event that ended.
            event_duration (float): The duration (in seconds) for which the event persisted.
        """
        # Map event names to human-readable descriptions and emojis
        event_descriptions = {
            "cpu_usage_exceeded": "🔥 *CPU usage normalized* 🔥",
            "memory_usage_exceeded": "🧠 *Memory usage normalized* 🧠",
            "disk_usage_exceeded_": "💽 *Disk usage normalized* 💽",
            "cpu_temp_exceeded": "🌡️ *CPU temperature normalized* 🌡️",
            "gpu_temp_exceeded": "🌡️ *GPU temperature normalized* 🌡️",
            "disk_temp_exceeded": "🌡️ *Disk temperature normalized* 🌡️",
            "pch_temp_exceeded": "🌡️ *PCH temperature normalized* 🌡️"
        }

        # Find the appropriate description
        for key, description in event_descriptions.items():
            if event_name.startswith(key):
                message = f"{description}\n⏱️ Duration: {int(event_duration)} seconds"
                self._send_notification(message)
                break

    def _get_temp_threshold(self, sensor: str) -> float:
        """
        Returns the temperature threshold for the given sensor.

        Args:
            sensor (str): The name of the sensor (e.g., "CPU", "GPU", "Disk", "PCH").

        Returns:
            float: The temperature threshold for the specified sensor.
        """
        temp_thresholds = {
            "CPU": self.cpu_temperature_threshold,
            "Disk": self.disk_temperature_threshold,
            "GPU": self.gpu_temperature_threshold,
            "PCH": self.pch_temperature_threshold
        }

        # Return the threshold for the sensor, or a default value if sensor is unknown
        return temp_thresholds.get(sensor, 80.0)  # 80°C as a default threshold

    def _send_aggregated_notifications(self, cpu_usage: float, memory_usage: float, disk_usage: dict,
                                       temperatures: dict,
                                       event_durations: dict) -> None:
        """
        Aggregates notifications based on monitored values and sends a single message if thresholds are exceeded.

        Args:
            cpu_usage (float): Current CPU usage.
            memory_usage (float): Current memory usage.
            disk_usage (dict): Current disk usage per disk.
            temperatures (dict): Current temperatures per sensor.
            event_durations (dict): Event durations for disk usage and temperatures.
        """
        messages = []

        # CPU usage notification
        cpu_event_duration = self._track_event_duration("cpu_usage_exceeded", cpu_usage > self.cpu_usage_threshold)
        if cpu_event_duration and cpu_event_duration >= self.event_threshold_duration:
            messages.append(
                f"🔥 *High CPU Usage Detected!* 🔥\n💻 CPU Usage: *{cpu_usage}%*\n⏱️ Duration: {int(cpu_event_duration)} seconds")

        # Memory usage notification
        mem_event_duration = self._track_event_duration("memory_usage_exceeded",
                                                        memory_usage >
                                                        self.monitor_settings.tracehold.memory_usage_threshold[0])
        if mem_event_duration and mem_event_duration >= self.event_threshold_duration:
            messages.append(
                f"🚨 *High Memory Usage Detected!* 🚨\n🧠 Memory Usage: *{memory_usage}%*\n⏱️ Duration: {int(mem_event_duration)} seconds")

        # Disk usage notifications
        for disk, usage in disk_usage.items():
            disk_event_duration = event_durations["disk_usage"].get(disk)
            if disk_event_duration and disk_event_duration >= self.event_threshold_duration:
                messages.append(
                    f"💽 *High Disk Usage Detected on {disk}!* 💽\n📊 Disk Usage: *{usage}%*\n⏱️ Duration: {int(disk_event_duration)} seconds")

        # Temperature notifications
        for sensor, temp in temperatures.items():
            temp_event_duration = event_durations["temperatures"].get(sensor)
            if temp_event_duration and temp_event_duration >= self.event_threshold_duration:
                messages.append(
                    f"🌡️ *{sensor} temperature is high:* {temp}°C\n⏱️ Duration: {int(temp_event_duration)} seconds")

        if messages and self.notification_count < self.max_notifications:
            aggregated_message = "\n\n".join(messages)
            self.bot_logger.debug(f"Monitoring aggregated notification sent: {aggregated_message}")
            self._send_notification(aggregated_message)

            self.notification_count += 1
            threading.Timer(300, self._reset_notification_count).start()

    def _send_notification(self, message: str) -> None:
        """
        Sends a notification message to the Telegram bot chat.
        If the maximum number of notifications has been reached, no further notifications will be sent.
        """
        if self.notification_count < self.max_notifications:
            try:
                sanitized_message = message.replace(self.config.emoji_for_notification, "").replace("\n", " ")
                self.bot_logger.info(f"Sending notification: {sanitized_message}")
                self.bot.send_message(self.settings.chat_id.global_chat_id[0], message, parse_mode="Markdown")
            except Exception as e:
                self.bot_logger.error(f"Failed to send notification: {e}")
        elif not self.max_notifications_reached:
            self.bot_logger.warning("Max notifications reached; no more notifications will be sent.")
            self.max_notifications_reached = True

    def _adjust_check_interval(self) -> None:
        """Adjust the check interval based on current CPU load."""
        cpu_load = psutil.cpu_percent(interval=1)
        if cpu_load > self.load_threshold:
            self.check_interval = 10  # Increase interval if load is high
            self.bot_logger.info(
                f"High CPU load detected ({cpu_load}%). Increasing check interval to {self.check_interval} seconds."
            )
        else:
            self.check_interval = self.monitor_settings.check_interval[0]  # Restore to normal interval

    def _check_temperatures(self) -> dict:
        """Checks the current temperatures of system components."""
        temperatures = {}
        try:
            temps = psutil.sensors_temperatures()
            if not temps and self.sensors_available:
                self.sensors_available = False
                self.bot_logger.warning("No temperature sensors available on this system.")
                return temperatures

            for name, entries in temps.items():
                for entry in entries:
                    temperatures[name] = entry.current

            return temperatures
        except psutil.Error as e:
            self.bot_logger.error(f"Error checking temperatures: {e}")

        return temperatures

    def _check_cpu_usage(self) -> float:
        """Checks the current CPU usage."""
        try:
            cpu_usage = psutil.cpu_percent(interval=1)
            return cpu_usage
        except psutil.Error as e:
            self.bot_logger.error(f"Error checking CPU usage: {e}")
            return 0.0

    def _check_memory_usage(self) -> float:
        """Checks the current memory usage."""
        try:
            memory = psutil.virtual_memory()
            return memory.percent
        except psutil.Error as e:
            self.bot_logger.error(f"Error checking memory usage: {e}")
            return 0.0

    def _check_disk_usage(self) -> dict:
        """Checks the current disk usage for all physical partitions."""
        disk_usage = {}
        try:
            partitions = psutil.disk_partitions(all=False)
            for partition in partitions:
                usage = psutil.disk_usage(partition.mountpoint)
                disk_usage[partition.device] = usage.percent
        except psutil.Error as e:
            self.bot_logger.error(f"Error retrieving disk partitions: {e}")

        return disk_usage

    def _reset_notification_count(self) -> None:
        """
        Resets the notification count to 0 after a specified delay.
        """
        self.notification_count = 0
        self.max_notifications_reached = False
        self.bot_logger.info("Notification count has been reset.")
