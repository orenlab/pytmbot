#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>

Monitor plugin for pyTMBot

pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""
import platform
import threading
import time
from typing import Optional

import psutil
from telebot import TeleBot

from pytmbot.adapters.docker.containers_info import fetch_docker_counters, retrieve_containers_stats
from pytmbot.adapters.docker.images_info import fetch_image_details
from pytmbot.db.influxdb_interface import InfluxDBInterface
from pytmbot.models.settings_model import MonitorConfig
from pytmbot.plugins.plugins_core import PluginCore
from pytmbot.settings import settings
from pytmbot.utils.utilities import is_running_in_docker


class SystemMonitorPlugin(PluginCore):
    """
    A plugin for monitoring system resources such as CPU, memory, disk usage, and temperatures.
    Sends notifications to a Telegram bot if any of the monitored resources exceed specified thresholds.
    """

    def __init__(self, config: "MonitorConfig", bot: TeleBot, event_threshold_duration: int = 40) -> None:
        """
        Initializes the SystemMonitorPlugin with the given bot instance and configuration.

        Args:
            config (MonitorConfig): Configuration for the SystemMonitorPlugin.
            bot (TeleBot): An instance of TeleBot to interact with Telegram API.
            event_threshold_duration (int): Minimum duration (in seconds) that a threshold event must persist
                                             before sending a notification. Defaults to 60 seconds.
        """
        super().__init__()
        self._init_mode = True
        self.bot = bot
        self.config = config
        self._monitoring = False
        self.notification_count = 0
        self.monitor_settings = self.settings.plugins_config.monitor
        self.max_notifications = self.monitor_settings.max_notifications[0]
        self._retry_attempts = self.monitor_settings.retry_attempts[0]
        self._retry_interval = self.monitor_settings.retry_interval[0]
        self.check_interval = self.monitor_settings.check_interval[0]
        self.monitor_docker = self.monitor_settings.monitor_docker
        self.event_threshold_duration = event_threshold_duration

        # Monitoring thresholds
        self.temperature_thresholds = {
            "cpu": self.monitor_settings.tracehold.cpu_temperature_threshold[0],
            "pch": self.monitor_settings.tracehold.cpu_temperature_threshold[0],
            "gpu": self.monitor_settings.tracehold.gpu_temperature_threshold[0],
            "disk": self.monitor_settings.tracehold.disk_temperature_threshold[0]
        }
        self.cpu_usage_threshold = self.monitor_settings.tracehold.cpu_usage_threshold[0]
        self.disk_usage_threshold = self.monitor_settings.tracehold.disk_usage_threshold[0]
        self.load_threshold = 70.0

        # InfluxDB settings
        self.influxdb_url = settings.influxdb.url[0].get_secret_value()
        self.influxdb_token = settings.influxdb.token[0].get_secret_value()
        self.influxdb_org = settings.influxdb.org[0].get_secret_value()
        self.influxdb_bucket = settings.influxdb.bucket[0].get_secret_value()
        self.influxdb_client = InfluxDBInterface(
            url=self.influxdb_url,
            token=self.influxdb_token,
            org=self.influxdb_org,
            bucket=self.influxdb_bucket
        )

        # Check if running in Docker
        self.is_docker = is_running_in_docker()

        # Store Docker counters
        self.docker_counters_last_updated = 0
        self.docker_counters_update_interval = 5 * 60

        # Store previous container and image hashes
        self._previous_container_hashes = {}
        self._previous_image_hashes = {}
        self._previous_counts = {
            'containers_count': 0,
            'images_count': 0
        }

        # Initialize state tracking for event durations
        self.event_start_times = {}

        # Track fan availability
        self.is_fans_sensors_available_logged = True

        # Check if sensors are available
        self.sensors_available = True

        self.last_disk_usage = {}
        self.last_poll_time = 0
        self.poll_interval = 10 * 60
        self.return_cached_disk_usage = False

    def start_monitoring(self) -> None:
        """
        Starts the system monitoring process in a separate thread.
        If the monitoring fails to start, it will retry up to `max_attempts` times.
        """
        if not self._monitoring:
            self._monitoring = True
            max_attempts = self._retry_attempts
            for attempt in range(max_attempts):
                try:
                    self._start_monitoring_thread()
                    return
                except Exception as e:
                    self.bot_logger.error(
                        f"Failed to start monitoring on attempt {attempt + 1}: {e}"
                    )
                    time.sleep(self._retry_interval)

            self.bot_logger.error(
                "Failed to start system monitoring after multiple attempts. Manual restart required."
            )
        else:
            self.bot_logger.warning("Monitoring is already running.")

    def _start_monitoring_thread(self) -> None:
        """
        Starts the system monitoring process in a separate daemon thread.
        """
        monitoring_thread = threading.Thread(
            target=self._monitor_system, daemon=True
        )
        monitoring_thread.name = "SystemMonitoringThread"
        monitoring_thread.start()

    def stop_monitoring(self) -> None:
        """
        Stops the system monitoring process.
        """
        if self._monitoring:
            self._monitoring = False
            self.bot_logger.info("System monitoring stopped.")
        else:
            self.bot_logger.warning("Monitoring is not running.")

    def _monitor_system(self) -> None:
        """
        Monitors the system and sends metrics to InfluxDB.
        """
        disk_usage_event_durations = {}
        temperature_event_durations = {}
        fan_speed_event_durations = {}

        try:
            while self._monitoring:
                self._adjust_check_interval()

                cpu_usage = self._check_cpu_usage()
                memory_usage = self._check_memory_usage()
                disk_usage = self._get_disk_usage()
                temperatures = self._check_temperatures()
                fan_speeds = self._get_fan_speeds()
                load_averages = self._check_load_average()

                # Track disk usage events individually for each disk
                for disk, usage in disk_usage.items():
                    disk_usage_event_duration = self._track_event_duration(
                        f"disk_{disk}_usage", usage > self.disk_usage_threshold
                    )
                    disk_usage_event_durations[disk] = disk_usage_event_duration

                # Track temperatures individually for each sensor
                for sensor, temp_data in temperatures.items():
                    temperature_event_duration = self._track_event_duration(
                        f"temperature_{sensor}",
                        temp_data["current"] > self._get_temp_threshold(sensor),
                    )
                    temperature_event_durations[sensor] = temperature_event_duration

                # Track fan speeds individually for each fan
                for fan, speed in fan_speeds.items():
                    fan_speed_event_duration = self._track_event_duration(
                        f"fan_{fan}_speed",
                        speed["current"] > self.config.fan_speed_threshold,
                    )
                    fan_speed_event_durations[fan] = fan_speed_event_duration

                # Collect metrics and metadata
                fields = {
                    "cpu_usage": cpu_usage,
                    "memory_usage": memory_usage,
                    "load_average_1m": load_averages[0],
                    "load_average_5m": load_averages[1],
                    "load_average_15m": load_averages[2],
                    **{
                        f"disk_{key}_usage": value
                        for key, value in disk_usage.items()
                    },
                    **{
                        f"temperature_{sensor}_current": temp_data["current"]
                        for sensor, temp_data in temperatures.items()
                    },
                    **{
                        f"temperature_{sensor}_high": temp_data["high"]
                        for sensor, temp_data in temperatures.items()
                        if temp_data["high"] is not None
                    },
                    **{
                        f"temperature_{sensor}_critical": temp_data["critical"]
                        for sensor, temp_data in temperatures.items()
                        if temp_data["critical"] is not None
                    },
                    **{
                        f"fan_{fan}_speed": speed["current"]
                        for fan, speed in fan_speeds.items()
                    },
                }

                if self.monitor_docker:
                    current_time = time.time()
                    if current_time - self.docker_counters_last_updated > self.docker_counters_update_interval:
                        self._detect_docker_changes()
                        self.docker_counters_last_updated = current_time
                        self.bot_logger.debug(
                            f"Updated Docker counters: {self._previous_counts}")

                fields.update(
                    **{
                        f"docker_{key}": value
                        for key, value in self._previous_counts.items()
                    }
                )

                self._record_metrics(fields)

                time.sleep(self.check_interval)
        except Exception as e:
            self.bot_logger.exception(f"Unexpected error during system monitoring: {e}")
            self.monitoring = False

    def _get_platform_metadata(self) -> dict:
        """Get the metadata for the current platform."""
        os_info = platform.uname()
        return {
            "system": "docker" if self.is_docker else "bare-metal",
            "hostname": os_info.node
        }

    def _record_metrics(self, fields: dict) -> None:
        """Record system metrics to InfluxDB."""
        try:
            metadata = self._get_platform_metadata()

            # Write metrics and metadata to InfluxDB
            with self.influxdb_client as client:
                client.write_data("system_metrics", fields, metadata)
        except Exception as e:
            self.bot_logger.exception(f"Error writing metrics to InfluxDB: {e}")

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

        # Return the threshold for the sensor, or a default value if sensor is unknown
        return self.temperature_thresholds.get(sensor, 80.0)  # 80°C as a default threshold

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
                f"<b>🔥 High CPU Usage Detected! 🔥</b>\n"
                f"<b>💻 CPU Usage:</b> <i>{cpu_usage}%</i>\n"
                f"<b>⏱️ Duration:</b> {int(cpu_event_duration)} seconds"
            )

        # Memory usage notification
        mem_event_duration = self._track_event_duration("memory_usage_exceeded",
                                                        memory_usage >
                                                        self.monitor_settings.tracehold.memory_usage_threshold[0])
        if mem_event_duration and mem_event_duration >= self.event_threshold_duration:
            messages.append(
                f"<b>🚨 High Memory Usage Detected! 🚨</b>\n"
                f"<b>🧠 Memory Usage:</b> <i>{memory_usage}%</i>\n"
                f"<b>⏱️ Duration:</b> {int(mem_event_duration)} seconds"
            )

        # Disk usage notifications
        for disk, usage in disk_usage.items():
            disk_event_duration = event_durations["disk_usage"].get(disk)
            if disk_event_duration and disk_event_duration >= self.event_threshold_duration:
                messages.append(
                    f"<b>💽 High Disk Usage Detected on {disk}! 💽</b>\n"
                    f"<b>📊 Disk Usage:</b> <i>{usage}%</i>\n"
                    f"<b>⏱️ Duration:</b> {int(disk_event_duration)} seconds"
                )

        # Temperature notifications
        for sensor, temp in temperatures.items():
            temp_event_duration = event_durations["temperatures"].get(sensor)
            if temp_event_duration and temp_event_duration >= self.event_threshold_duration:
                messages.append(
                    f"<b>🌡️ {sensor} temperature is high:</b> <i>{temp}°C</i>\n"
                    f"<b>⏱️ Duration:</b> {int(temp_event_duration)} seconds"
                )

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
                self.bot.send_message(self.settings.chat_id.global_chat_id[0], message, parse_mode="HTML")
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
            self.bot_logger.warning(
                f"High CPU load detected ({cpu_load}%). Increasing check interval to {self.check_interval} seconds."
            )
        else:
            self.check_interval = self.monitor_settings.check_interval[0]  # Restore to normal interval

    def _check_load_average(self) -> tuple[float, float, float]:
        """
        Checks the current load average (1, 5, and 15 minutes).
        """
        try:
            load_avg_1, load_avg_5, load_avg_15 = psutil.getloadavg()  # Get the 1, 5, and 15 minute load averages
            return load_avg_1, load_avg_5, load_avg_15
        except (AttributeError, psutil.Error) as e:
            self.bot_logger.error(f"Error checking load average: {e}")
            return 0.0, 0.0, 0.0

    def _check_temperatures(self) -> dict:
        """Checks the current temperatures of system components and captures high/critical thresholds."""
        temperatures = {}
        try:
            temps = psutil.sensors_temperatures()
            if not temps and self.sensors_available:
                self.sensors_available = False
                self.bot_logger.warning("No temperature sensors available on this system.")
                return temperatures

            for name, entries in temps.items():
                for entry in entries:
                    sensor_key = f"{name}_{entry.label or 'default'}"  # Use label if available, else 'default'
                    temperatures[sensor_key] = {
                        "current": entry.current,
                        "high": entry.high if entry.high else None,  # High threshold, if available
                        "critical": entry.critical if entry.critical else None  # Critical threshold, if available
                    }

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

    @staticmethod
    def _is_partition_excluded(partition: str) -> bool:
        """
        Checks if the given partition should be excluded from monitoring.

        Args:
            partition (str): The name of the partition to check.

        Returns:
            bool: True if the partition should be excluded, False otherwise.
        """
        excluded_keywords = {
            "loop",
            "tmpfs",
            "devtmpfs",
            "proc",
            "sysfs",
            "cgroup",
            "mqueue",
            "hugetlbfs",
            "overlay",
            "aufs",
        }
        return any(keyword in partition for keyword in excluded_keywords)

    def _get_disk_usage(self) -> dict:
        """Returns the current disk usage for all physical partitions, excluding certain keywords."""
        current_time = time.time()

        if current_time - self.last_poll_time >= self.poll_interval:
            disk_usage = {}
            try:
                partitions = psutil.disk_partitions(all=False)
                for partition in partitions:
                    if not self._is_partition_excluded(partition.device):
                        disk_usage[partition.device] = psutil.disk_usage(partition.mountpoint).percent
                self.last_disk_usage = disk_usage
                self.last_poll_time = current_time
                self.return_cached_disk_usage = True
            except psutil.Error as e:
                self.bot_logger.error(f"Failed to retrieve disk partitions: {e}")
        else:
            if self.return_cached_disk_usage:
                self.bot_logger.debug("Returning cached disk usage data.")
                self.return_cached_disk_usage = False

        return self.last_disk_usage

    def _get_fan_speeds(self) -> dict[str, dict[str, int]]:
        """
        Checks the current fan speeds of system components.

        Returns:
            dict[str, dict[str, int]]: A dictionary with fan names as keys and dictionaries
                containing the current fan speed as values.
        """
        fan_speeds = {}
        try:
            for name, entries in psutil.sensors_fans().items():
                for entry in entries:
                    fan_speeds[f"{name}_{entry.label or 'default'}"] = {
                        "current": entry.current
                    }
            return fan_speeds
        except psutil.Error as e:
            self.bot_logger.error(f"Error checking fan speeds: {e}")

    def _get_docker_counters(self):
        """Retrieves Docker counters: number of images and containers."""
        try:
            return fetch_docker_counters()
        except Exception as e:
            self.bot_logger.error(f"Error retrieving docker counters: {e}")
            return {}

    def _send_detailed_container_notification(self, container_context):
        """
        Sends a detailed notification about a new container.
        """
        message = (
            f"🚨 <b>Potential Security Incident: New Docker Container</b> 🚨\n"
            f"📦 <b>Name:</b> <i>{container_context['name']}</i>\n"
            f"🖼️ <b>Image:</b> <i>{container_context['image']}</i>\n"
            f"🕒 <b>Created:</b> <i>{container_context['created']}</i>\n"
            f"🚀 <b>Running Since:</b> <i>{container_context['run_at']}</i>\n"
            f"📊 <b>Status:</b> <i>{container_context['status']}</i>\n"
            "Please review this new container."
        )
        self._send_notification(message)

    def _send_detailed_image_notification(self, image_context):
        """
        Sends a detailed notification about a new Docker image.
        """
        message = (
            f"🚨 <b>Potential Security Incident: New Docker Image</b> 🚨\n"
            f"🖼️ <b>ID:</b> <i>{image_context['id']}</i>\n"
            f"🏷️ <b>Tags:</b> <i>{', '.join(image_context['tags'])}</i>\n"
            f"🔧 <b>Architecture:</b> <i>{image_context['architecture']}</i>\n"
            f"💻 <b>OS:</b> <i>{image_context['os']}</i>\n"
            f"📦 <b>Size:</b> <i>{image_context['size']}</i>\n"
            f"🕒 <b>Created:</b> <i>{image_context['created']}</i>\n"
            "Please review this new image."
        )
        self._send_notification(message)

    def _reset_notification_count(self) -> None:
        """
        Resets the notification count to 0 after a specified delay.
        """
        self.notification_count = 0
        self.max_notifications_reached = False
        self.bot_logger.info("Notification count has been reset.")

    def _get_docker_status(self):
        """
        Get the current Docker status.
        """
        new_counts = self._get_docker_counters()
        new_containers = retrieve_containers_stats()
        new_images = fetch_image_details()

        return new_counts, new_containers, new_images

    def _detect_docker_changes(self):
        """
        Detects changes in running Docker containers and images, and sends notifications if new ones are found.
        Uses unique identifiers (hashes) for efficient tracking.
        """
        new_counts, new_containers, new_images = self._get_docker_status()

        # Create hashes for the new containers and images
        new_container_hashes = {
            container['id']: container
            for container in new_containers
        }

        new_image_hashes = {
            image['id']: image
            for image in new_images
        }

        if self._init_mode:
            self._init_mode = False
            self.bot_logger.info(
                f"Init Docker containers and images monitoring with {len(new_container_hashes)} containers and {len(new_image_hashes)} images.")
            self.bot_logger.debug(f"Known containers: {new_container_hashes}")
            self.bot_logger.debug(f"Known images: {new_image_hashes}")
        else:
            # Detect new containers
            new_container_ids = new_container_hashes.keys() - self._previous_container_hashes.keys()
            for container_id in new_container_ids:
                self._send_detailed_container_notification(new_container_hashes[container_id])

            # Detect new images
            new_image_ids = new_image_hashes.keys() - self._previous_image_hashes.keys()
            for image_id in new_image_ids:
                self._send_detailed_image_notification(new_image_hashes[image_id])

        # Update previous hashes and counts
        self._previous_container_hashes = new_container_hashes
        self._previous_image_hashes = new_image_hashes
        self._previous_counts = new_counts
