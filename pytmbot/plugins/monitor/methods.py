#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping, Sequence
from typing import Literal

from telebot import TeleBot

from pytmbot.adapters.docker.containers_info import (
    retrieve_containers_stats,
)
from pytmbot.adapters.docker.images_info import fetch_image_details
from pytmbot.adapters.psutil.adapter import PsutilAdapter
from pytmbot.adapters.psutil.adapter_types import TopProcess
from pytmbot.db.influxdb_interface import InfluxDBConfig, InfluxDBInterface
from pytmbot.logs import Logger
from pytmbot.plugins.monitor.models import MonitoringState, ResourceThresholds
from pytmbot.plugins.monitor.utils import (
    EventTracker,
    SystemInfo,
    SystemMetrics,
)
from pytmbot.plugins.plugins_core import PluginCore
from pytmbot.utils import is_running_in_docker, set_naturalsize

logger = Logger()


class SystemMonitorPlugin(PluginCore):
    """Plugin for monitoring system resources."""

    DEFAULT_DOCKER_COUNTERS_UPDATE_INTERVAL_SECONDS = 300
    DEFAULT_NOTIFICATION_RESET_WINDOW_SECONDS = 300
    MAX_CHECK_INTERVAL_SECONDS = 30
    MONITOR_THREAD_JOIN_TIMEOUT_SECONDS = 2

    __slots__ = (
        "bot",
        "monitor_settings",
        "event_threshold_duration",
        "state",
        "thresholds",
        "_previous_container_hashes",
        "_previous_image_hashes",
        "_previous_counts",
        "_known_container_ids",
        "_known_image_ids",
        "influxdb_client",
        "is_docker",
        "check_interval",
        "docker_counters_update_interval",
        "system_metrics",
        "_platform_metadata",
        "_active_event_ids",
        "_notification_reset_window_seconds",
        "_monitor_thread",
        "_supervisor_thread",
        "_supervisor_stop_event",
        "_monitor_thread_lock",
        "_monitor_restart_count",
        "_psutil_adapter",
    )

    def __init__(self, bot: TeleBot, event_threshold_duration: float = 20) -> None:
        super().__init__()

        self.bot = bot
        plugins_config = self.settings.plugins_config
        monitor_settings = plugins_config.monitor if plugins_config else None
        if monitor_settings is None:
            raise RuntimeError("Monitor plugin configuration is missing")

        self.monitor_settings = monitor_settings
        self.event_threshold_duration = event_threshold_duration

        # Initialize state and thresholds
        self.state = MonitoringState()
        self.thresholds = ResourceThresholds(
            cpu_temp=self.monitor_settings.tracehold.cpu_temperature_threshold[0],
            gpu_temp=self.monitor_settings.tracehold.gpu_temperature_threshold[0],
            disk_temp=self.monitor_settings.tracehold.disk_temperature_threshold[0],
            pch_temp=self.monitor_settings.tracehold.cpu_temperature_threshold[0],
            cpu_usage=self.monitor_settings.tracehold.cpu_usage_threshold[0],
            memory_usage=self.monitor_settings.tracehold.memory_usage_threshold[0],
            disk_usage=self.monitor_settings.tracehold.disk_usage_threshold[0],
        )

        # Docker monitoring state
        self._previous_container_hashes: dict[str, Mapping[str, object]] = {}
        self._previous_image_hashes: dict[str, Mapping[str, object]] = {}
        self._previous_counts: dict[str, int] = {
            "containers_count": 0,
            "images_count": 0,
        }

        # Add sets to track all historically seen containers and images
        self._known_container_ids: set[str] = set()
        self._known_image_ids: set[str] = set()

        # Initialize InfluxDB and system detection
        self._init_influxdb()
        self.is_docker = is_running_in_docker()
        self._platform_metadata = self._build_platform_metadata()

        # Set monitoring intervals
        self.check_interval = max(1, int(self.monitor_settings.check_interval[0]))
        self.docker_counters_update_interval = (
            self.DEFAULT_DOCKER_COUNTERS_UPDATE_INTERVAL_SECONDS
        )
        self._notification_reset_window_seconds = (
            self._resolve_notification_reset_window_seconds()
        )
        self._active_event_ids: dict[str, str] = {}

        self._psutil_adapter = PsutilAdapter()
        self.system_metrics = SystemMetrics(psutil_adapter=self._psutil_adapter)
        self._monitor_thread: threading.Thread | None = None
        self._supervisor_thread: threading.Thread | None = None
        self._supervisor_stop_event = threading.Event()
        self._monitor_thread_lock = threading.RLock()
        self._monitor_restart_count = 0

    def _build_platform_metadata(self) -> dict[str, str]:
        return {
            key: str(value)
            for key, value in SystemInfo.get_platform_metadata(self.is_docker).items()
        }

    def _init_influxdb(self) -> None:
        try:
            influxdb_config = self.settings.influxdb
            if influxdb_config is None or (
                influxdb_config.url is None
                or influxdb_config.token is None
                or influxdb_config.org is None
                or influxdb_config.bucket is None
            ):
                raise RuntimeError("InfluxDB configuration is missing required fields")

            self.influxdb_client = InfluxDBInterface(
                InfluxDBConfig(
                    url=influxdb_config.url[0].get_secret_value(),
                    token=influxdb_config.token[0].get_secret_value(),
                    org=influxdb_config.org[0].get_secret_value(),
                    bucket=influxdb_config.bucket[0].get_secret_value(),
                    debug_mode=influxdb_config.debug_mode,
                )
            )
        except Exception as e:
            logger.error("bot.plugins.monitor.methods.initialize.influx.fail", e)
            raise

    def start_monitoring(self) -> None:
        if self.state.is_active:
            return

        self._supervisor_stop_event.clear()
        self.state.is_active = True
        self._monitor_restart_count = 0

        retry_attempts = self.monitor_settings.retry_attempts[0]
        retry_interval = max(1, self.monitor_settings.retry_interval[0])

        for attempt in range(retry_attempts):
            try:
                self.influxdb_client.connect()
                with self._monitor_thread_lock:
                    self._monitor_thread = self._spawn_monitor_thread()
                    self._supervisor_thread = threading.Thread(
                        target=self._supervise_monitoring,
                        name="SystemMonitorSupervisorThread",
                        daemon=True,
                    )
                    self._supervisor_thread.start()

                with logger.context(
                    context={
                        "component": "monitoring",
                        "action": "start",
                        "attempt": attempt,
                        "tracehold": self.monitor_settings.tracehold,
                        "event_threshold_duration": self.event_threshold_duration,
                        "check_interval": self.check_interval,
                        "docker_counters_update_interval": self.docker_counters_update_interval,
                        "is_docker": self.is_docker,
                    }
                ) as log:
                    log.info("bot.plugins.monitor.methods.monitoring.start")
                return
            except Exception as e:
                logger.error("bot.plugins.monitor.methods.monitoring.start.fail", e)
                try:
                    self.influxdb_client.close()
                except Exception as close_error:
                    logger.error(
                        "bot.plugins.monitor.methods.monitoring.start.fail", close_error
                    )
                if attempt < retry_attempts - 1:
                    time.sleep(retry_interval)
                else:
                    self.state.is_active = False
                    raise RuntimeError(
                        "Failed to start monitoring after maximum attempts"
                    ) from e

    def _spawn_monitor_thread(self) -> threading.Thread:
        """Create and start monitor worker thread."""
        thread = threading.Thread(
            target=self._monitor_system,
            name="SystemMonitorThread",
            daemon=True,
        )
        thread.start()
        return thread

    def _supervise_monitoring(self) -> None:
        """Watch monitor worker and restart it if it dies unexpectedly."""
        retry_interval = max(1, self.monitor_settings.retry_interval[0])
        while self.state.is_active:
            try:
                with self._monitor_thread_lock:
                    monitor_thread = self._monitor_thread
                    should_restart = (
                        monitor_thread is None or not monitor_thread.is_alive()
                    )
                    if should_restart:
                        self._monitor_thread = self._spawn_monitor_thread()
                        self._monitor_restart_count += 1
                        logger.warning(
                            "bot.plugins.monitor.methods.monitoring.restarted.warn",
                            extra={"restart_count": self._monitor_restart_count},
                        )
            except Exception as e:
                logger.error(
                    "bot.plugins.monitor.methods.monitoring.supervisor.fail", e
                )
            if self._supervisor_stop_event.wait(timeout=retry_interval):
                break

    def _monitor_system(self) -> None:
        while self.state.is_active:
            try:
                cycle_cpu_usage = self._adjust_check_interval()

                # Collect and process metrics
                metrics: dict[str, object] = dict(
                    self.system_metrics.collect_metrics(cpu_usage=cycle_cpu_usage)
                )
                if self.monitor_settings.monitor_docker:
                    self._process_docker_metrics(metrics)

                # Record metrics and process alerts
                self._record_metrics(metrics)
                self._process_alerts(metrics)

                time.sleep(self.check_interval)

            except Exception as e:
                logger.error("bot.plugins.monitor.methods.monitoring.cycle.fail", e)
                time.sleep(max(1, self.check_interval // 2))

    def _process_alerts(self, metrics: dict[str, object]) -> None:
        cpu_usage = metrics.get("cpu_usage")
        if isinstance(cpu_usage, (int, float)):
            self._check_cpu_alert(float(cpu_usage))

        memory_usage = metrics.get("memory_usage")
        if isinstance(memory_usage, (int, float)):
            self._check_memory_alert(float(memory_usage))

        temperatures = metrics.get("temperatures")
        if isinstance(temperatures, dict):
            self._check_temperature_alerts(temperatures)
        disk_usage = metrics.get("disk_usage")
        if isinstance(disk_usage, dict):
            self._check_disk_alerts(disk_usage)

    def _find_active_event_id(self, event_type: str) -> str | None:
        """Return unresolved event id by type."""
        indexed_event_id = self._active_event_ids.get(event_type)
        if indexed_event_id is not None:
            indexed_event = self.state.active_events.get(indexed_event_id)
            if indexed_event and not indexed_event["resolved"]:
                return indexed_event_id
            self._active_event_ids.pop(event_type, None)

        for event_id, event in self.state.active_events.items():
            if event["type"] == event_type and not event["resolved"]:
                self._active_event_ids[event_type] = event_id
                return event_id
        return None

    def _create_or_notify_event(
        self,
        event_type: str,
        details: dict[str, object],
        message_formatter: Callable[..., str],
        *message_args: object,
    ) -> None:
        """Create event if absent and send alert notification."""
        event_id = self._find_active_event_id(event_type)
        if event_id:
            return

        event_id = EventTracker.create_event(self.state, event_type, details)
        self._active_event_ids[event_type] = event_id
        self._send_notification(message_formatter(event_id, *message_args))

    def _resolve_event_and_notify(self, event_type: str, label: str) -> None:
        """Resolve all active events for type and send resolution notifications."""
        event_ids_to_remove: list[str] = []
        for event_id, event in self.state.active_events.items():
            if event["type"] != event_type or event["resolved"]:
                continue
            duration = EventTracker.resolve_event(self.state, event_id)
            if duration:
                self._send_resolution_notification(label, duration)
            event_ids_to_remove.append(event_id)

        for event_id in event_ids_to_remove:
            self.state.active_events.pop(event_id, None)
            if self._active_event_ids.get(event_type) == event_id:
                self._active_event_ids.pop(event_type, None)

    def _check_cpu_alert(self, usage: float) -> None:
        if usage > self.thresholds.cpu_usage:
            self._create_or_notify_event(
                "cpu_usage",
                {"usage": usage},
                self._format_cpu_alert,
                usage,
            )
        else:
            self._resolve_event_and_notify("cpu_usage", "CPU usage")

    def _check_memory_alert(self, usage: float) -> None:
        if usage > self.thresholds.memory_usage:
            self._create_or_notify_event(
                "memory_usage",
                {"usage": usage},
                self._format_memory_alert,
                usage,
            )
        else:
            self._resolve_event_and_notify("memory_usage", "Memory usage")

    def _check_temperature_alerts(
        self, temperatures: dict[str, dict[str, float | None]]
    ) -> None:
        for sensor, data in temperatures.items():
            current_temp = data.get("current")
            if not isinstance(current_temp, (int, float)):
                continue
            threshold = self._resolve_temperature_threshold(sensor)
            if current_temp > threshold:
                event_type = f"temp_{sensor}"
                self._create_or_notify_event(
                    event_type,
                    {"temperature": current_temp, "sensor": sensor},
                    self._format_temperature_alert,
                    sensor,
                    data,
                )
            else:
                self._resolve_event_and_notify(
                    f"temp_{sensor}", f"Temperature ({sensor})"
                )

    def _resolve_temperature_threshold(self, sensor: str) -> float:
        """Map psutil sensor names to configured monitor thresholds."""
        sensor_key = sensor.lower()
        if "gpu" in sensor_key or "amdgpu" in sensor_key or "nvidia" in sensor_key:
            return self.thresholds.gpu_temp
        if "nvme" in sensor_key or "disk" in sensor_key or "ssd" in sensor_key:
            return self.thresholds.disk_temp
        if "pch" in sensor_key:
            return self.thresholds.pch_temp
        return self.thresholds.cpu_temp

    def _check_disk_alerts(self, disk_usage: dict[str, float]) -> None:
        for disk, usage in disk_usage.items():
            if usage > self.thresholds.disk_usage:
                event_type = f"disk_{disk}"
                self._create_or_notify_event(
                    event_type,
                    {"usage": usage, "disk": disk},
                    self._format_disk_alert,
                    disk,
                    usage,
                )
            else:
                self._resolve_event_and_notify(f"disk_{disk}", f"Disk usage ({disk})")

    @staticmethod
    def _build_docker_counters(
        containers: Sequence[Mapping[str, object]],
        images: Sequence[Mapping[str, object]],
    ) -> dict[str, int]:
        containers_count = len(containers)
        running_containers = sum(
            1
            for container in containers
            if str(container.get("status", "")).strip().lower() == "running"
        )
        return {
            "images_count": len(images),
            "containers_count": containers_count,
            "running_containers": running_containers,
            "stopped_containers": max(containers_count - running_containers, 0),
        }

    def _process_docker_metrics(self, metrics: dict[str, object]) -> None:
        current_time = time.time()
        if (
            current_time - self.state.docker_counters_last_updated
            >= self.docker_counters_update_interval
        ):
            try:
                new_containers = retrieve_containers_stats()
                new_images = fetch_image_details()
                new_counts = self._build_docker_counters(new_containers, new_images)

                self._detect_docker_changes(new_counts, new_containers, new_images)
                self.state.docker_counters_last_updated = current_time

                metrics.update(
                    {f"docker_{key}": value for key, value in new_counts.items()}
                )

            except Exception as e:
                logger.error("bot.plugins.monitor.methods.metrics.processing.fail", e)

    def _detect_docker_changes(
        self,
        new_counts: dict[str, int],
        new_containers: Sequence[Mapping[str, object]],
        new_images: Sequence[Mapping[str, object]],
    ) -> None:
        try:
            new_container_hashes: dict[str, Mapping[str, object]] = {}
            for container in new_containers:
                container_id = container.get("id")
                if isinstance(container_id, str):
                    new_container_hashes[container_id] = container

            new_image_hashes: dict[str, Mapping[str, object]] = {}
            for image in new_images:
                image_id = image.get("id")
                if isinstance(image_id, str):
                    new_image_hashes[image_id] = image

            if self.state.init_mode:
                # During initialization, add all current containers and images to known sets
                self._known_container_ids.update(new_container_hashes.keys())
                self._known_image_ids.update(new_image_hashes.keys())
                self.state.init_mode = False
                logger.info(
                    "bot.plugins.monitor.methods.monitoring.init",
                    extra={
                        "containers": len(new_container_hashes),
                        "images": len(new_image_hashes),
                    },
                )
            else:
                # Check for genuinely new containers (not seen before)
                new_container_ids = (
                    set(new_container_hashes.keys()) - self._known_container_ids
                )
                for container_id in new_container_ids:
                    self._send_container_notification(
                        new_container_hashes[container_id]
                    )
                    self._known_container_ids.add(container_id)

                # Check for genuinely new images (not seen before)
                new_image_ids = set(new_image_hashes.keys()) - self._known_image_ids
                for image_id in new_image_ids:
                    self._send_image_notification(new_image_hashes[image_id])
                    self._known_image_ids.add(image_id)

            # Update tracking state
            self._previous_container_hashes = new_container_hashes
            self._previous_image_hashes = new_image_hashes
            self._previous_counts = new_counts

        except Exception as e:
            logger.error("bot.plugins.monitor.methods.detect.changes.fail", e)

    def _record_metrics(self, fields: dict[str, object]) -> None:
        metadata = getattr(self, "_platform_metadata", None)
        if not metadata:
            metadata = self._build_platform_metadata()
            self._platform_metadata = metadata

        sanitized_fields = self._sanitize_fields(fields)
        numeric_fields = self._extract_numeric_fields(sanitized_fields)
        if not numeric_fields:
            logger.warning("bot.plugins.monitor.methods.metrics.empty.warn")
            return

        if not self.influxdb_client.write_data_async(
            "system_metrics", numeric_fields, metadata
        ):
            logger.warning("bot.plugins.monitor.methods.metrics.skipped.warn")
            return

        logger.debug("bot.plugins.monitor.methods.metrics.recorded.ok", extra=fields)

    @staticmethod
    def _sanitize_fields(
        fields: dict[str, object],
    ) -> dict[str, int | float | str | bool | None]:
        sanitized_fields: dict[str, int | float | str | bool | None] = {}
        for key, value in fields.items():
            if isinstance(value, (int, float, str, bool, type(None))):
                sanitized_fields[key] = value
                continue

            if isinstance(value, dict):
                for sub_key, sub_value in value.items():
                    if isinstance(sub_value, (int, float, bool)):
                        sanitized_fields[f"{key}_{sub_key}"] = sub_value
                    else:
                        logger.warning(
                            "bot.plugins.monitor.methods.unsupported.type.warn"
                        )
                continue

            if isinstance(value, tuple):
                for i, item in enumerate(value):
                    if isinstance(item, (int, float, bool)):
                        sanitized_fields[f"{key}_{i + 1}m"] = item
                    else:
                        logger.warning(
                            "bot.plugins.monitor.methods.unsupported.type.warn"
                        )
                continue

            logger.warning("bot.plugins.monitor.methods.unsupported.type.warn")
        return sanitized_fields

    @staticmethod
    def _extract_numeric_fields(
        fields: Mapping[str, int | float | str | bool | None],
    ) -> dict[str, float]:
        numeric_fields: dict[str, float] = {}
        for key, value in fields.items():
            if isinstance(value, bool):
                numeric_fields[key] = float(int(value))
            elif isinstance(value, (int, float)):
                numeric_fields[key] = float(value)
        return numeric_fields

    def _send_notification(
        self, message: str, *, count_towards_budget: bool = True
    ) -> None:
        current_time = time.time()
        if count_towards_budget:
            self._maybe_reset_notification_budget(current_time)

            if (
                self.state.notification_count
                >= self.monitor_settings.max_notifications[0]
            ):
                if not self.state.max_notifications_reached:
                    logger.warning(
                        "bot.plugins.monitor.methods.maximum.notifications.warn"
                    )
                    self.state.max_notifications_reached = True
                return

        try:
            self.bot.send_message(
                self.settings.chat_id.global_chat_id[0], message, parse_mode="HTML"
            )
            logger.info(
                "bot.plugins.monitor.methods.notification.sent.info",
                extra={"message": str(message)},
            )

            if count_towards_budget:
                self.state.notification_count += 1
                self.state.next_notification_reset_at = (
                    current_time + self._get_notification_reset_window_seconds()
                )

        except Exception as e:
            logger.error("bot.plugins.monitor.methods.send.notification.fail", e)

    def _resolve_notification_reset_window_seconds(self) -> int:
        """Resolve notification reset window from settings with safe fallback."""
        reset_window = self.monitor_settings.reset_notification_count[0]
        if isinstance(reset_window, int) and reset_window > 0:
            return reset_window
        return self.DEFAULT_NOTIFICATION_RESET_WINDOW_SECONDS

    def _get_notification_reset_window_seconds(self) -> int:
        cached_window = getattr(self, "_notification_reset_window_seconds", 0)
        if isinstance(cached_window, int) and cached_window > 0:
            return cached_window

        resolved_window = self._resolve_notification_reset_window_seconds()
        self._notification_reset_window_seconds = resolved_window
        return resolved_window

    def _maybe_reset_notification_budget(
        self, current_time: float | None = None
    ) -> None:
        """Reset notification counters lazily when reset deadline has passed."""
        now = current_time if current_time is not None else time.time()
        next_reset_at = self.state.next_notification_reset_at
        if next_reset_at > 0 and now >= next_reset_at:
            self._reset_notification_count()
            self.state.next_notification_reset_at = 0.0

    def _get_top_processes(self) -> list[TopProcess]:
        """Collect top processes once through shared psutil adapter."""
        try:
            return self._psutil_adapter.get_top_processes(count=5)
        except Exception as error:
            logger.warning(
                "bot.plugins.monitor.methods.top.processes.fail",
                extra={"error": str(error)},
            )
            return []

    def _format_cpu_alert(self, event_id: str, usage: float) -> str:
        """
        Format CPU alert message with top processes information.

        Args:
            event_id: Unique identifier for the alert event
            usage: Current CPU usage percentage

        Returns:
            Formatted alert message with top processes
        """
        process_info = self._format_process_info(
            self._get_top_processes(),
            resource_key="cpu_percent",
            suffix="% CPU",
        )

        return (
            f"🔥 <b>High CPU Usage Alert!</b> 🔥\n"
            f"Event ID: {event_id}\n"
            f"Current Usage: {usage:.1f}%\n\n"
            f"<b>Top CPU Consuming Processes:</b>\n"
            f"{process_info}"
        )

    def _format_memory_alert(self, event_id: str, usage: float) -> str:
        """
        Format memory alert message with top processes information.

        Args:
            event_id: Unique identifier for the alert event
            usage: Current memory usage percentage

        Returns:
            Formatted alert message with top processes
        """
        process_info = self._format_process_info(
            self._get_top_processes(),
            resource_key="memory_percent",
            suffix="% MEM",
        )

        return (
            f"🧠 <b>High Memory Usage Alert!</b> 🧠\n"
            f"Event ID: {event_id}\n"
            f"Current Usage: {usage:.1f}%\n\n"
            f"<b>Top Memory Consuming Processes:</b>\n"
            f"{process_info}"
        )

    @staticmethod
    def _format_process_info(
        processes: list[TopProcess],
        resource_key: Literal["cpu_percent", "memory_percent"],
        suffix: str = "%",
    ) -> str:
        """
        Format process information for alerts.

        Args:
            processes: List of process dictionaries with usage information
            resource_key: Key to sort and display resource usage ('cpu_percent' or 'memory_percent')
            suffix: Suffix to append to resource values (default: '%')

        Returns:
            Formatted string with process information
        """
        if not processes:
            return "  • N/A"
        return "\n".join(
            f"  • {proc['name']} (PID: {proc['pid']}) - "
            f"{proc[resource_key]:.1f}{suffix}"
            for proc in sorted(processes, key=lambda x: x[resource_key], reverse=True)
        )

    @staticmethod
    def _format_temperature_alert(
        event_id: str, sensor: str, data: dict[str, float | None]
    ) -> str:
        current_temp = data.get("current")
        current_temp_display = (
            f"{current_temp:.1f}°C" if isinstance(current_temp, (int, float)) else "N/A"
        )
        return (
            f"🌡️ <b>High Temperature Alert - {sensor}</b>\n"
            f"Event ID: {event_id}\n"
            f"Current: {current_temp_display}"
        )

    @staticmethod
    def _format_disk_alert(event_id: str, disk: str, usage: float) -> str:
        return (
            f"💽 <b>High Disk Usage Alert - {disk}</b>\n"
            f"Event ID: {event_id}\n"
            f"Current Usage: {usage:.1f}%"
        )

    def _send_container_notification(self, container: Mapping[str, object]) -> None:
        container_name = str(container.get("name", "unknown"))
        image_name = str(container.get("image", "unknown"))
        created_at = str(container.get("created", "unknown"))
        running_since = str(container.get("run_at", "unknown"))
        status = str(container.get("status", "unknown"))
        networks = str(container.get("networks", "N/A"))
        ports = str(container.get("ports", "N/A"))

        message = (
            "🚨 <b>Security Alert: New Docker Container Detected</b> 🚨\n"
            f"📦 <b>Name:</b> <i>{container_name}</i>\n"
            f"🖼️ <b>Image:</b> <i>{image_name}</i>\n"
            f"🕒 <b>Created:</b> <i>{created_at}</i>\n"
            f"🚀 <b>Running Since:</b> <i>{running_since}</i>\n"
            f"📊 <b>Status:</b> <i>{status}</i>\n"
            f"🔍 <b>Networks:</b> <i>{networks}</i>\n"
            f"🔌 <b>Ports:</b> <i>{ports}</i>\n"
            "⚠️ Please verify this container's authenticity and permissions."
        )
        self._send_notification(message)

    def _send_image_notification(self, image: Mapping[str, object]) -> None:
        image_id = str(image.get("id", "unknown"))[:12]
        image_tags_raw = image.get("tags")
        image_tags = (
            ", ".join(str(tag) for tag in image_tags_raw)
            if isinstance(image_tags_raw, list)
            else "None"
        )
        architecture = str(image.get("architecture", "unknown"))
        os_name = str(image.get("os", "unknown"))
        size_value = image.get("size")
        size_in_bytes = size_value if isinstance(size_value, (int, float)) else 0
        created_at = str(image.get("created", "unknown"))

        message = (
            "🚨 <b>Security Alert: New Docker Image Detected</b> 🚨\n"
            f"🖼️ <b>ID:</b> <i>{image_id}</i>\n"
            f"🏷️ <b>Tags:</b> <i>{image_tags}</i>\n"
            f"🔧 <b>Architecture:</b> <i>{architecture}</i>\n"
            f"💻 <b>OS:</b> <i>{os_name}</i>\n"
            f"📦 <b>Size:</b> <i>{set_naturalsize(size_in_bytes)}</i>\n"
            f"🕒 <b>Created:</b> <i>{created_at}</i>\n"
            "⚠️ Please verify this image's authenticity and source."
        )
        self._send_notification(message)

    def _send_resolution_notification(self, event_type: str, duration: float) -> None:
        message = (
            f"✅ <b>{event_type} has normalized</b>\nDuration: {int(duration)} seconds"
        )
        try:
            self._send_notification(message, count_towards_budget=False)
        except TypeError:
            # Keep compatibility with monkeypatched call-sites in tests.
            self._send_notification(message)

    def _reset_notification_count(self) -> None:
        self.state.notification_count = 0
        self.state.max_notifications_reached = False
        logger.debug("bot.plugins.monitor.methods.notification.counter.debug")

    def _adjust_check_interval(self) -> float | None:
        try:
            cpu_data = self._psutil_adapter.get_cpu_usage()
            raw_cpu_load = cpu_data.get("cpu_percent", 0.0)
            cpu_load = (
                float(raw_cpu_load) if isinstance(raw_cpu_load, (int, float)) else 0.0
            )
            if cpu_load > self.thresholds.load:
                new_interval = min(
                    self.check_interval * 2, self.MAX_CHECK_INTERVAL_SECONDS
                )
                if new_interval != self.check_interval:
                    self.check_interval = new_interval
                    logger.info(
                        "bot.plugins.monitor.methods.check.interval.info",
                        extra={"cpu_load": cpu_load, "new_interval": new_interval},
                    )
            else:
                self.check_interval = max(
                    1, int(self.monitor_settings.check_interval[0])
                )
            return cpu_load
        except Exception as e:
            logger.error("bot.plugins.monitor.methods.adjust.check.fail", e)
            return None

    def stop_monitoring(self) -> None:
        was_active = self.state.is_active
        self._supervisor_stop_event.set()
        if self.state.is_active:
            self.state.is_active = False
            with self._monitor_thread_lock:
                monitor_thread = self._monitor_thread
                supervisor_thread = self._supervisor_thread
                self._monitor_thread = None
                self._supervisor_thread = None

            current_thread = threading.current_thread()
            for thread in (monitor_thread, supervisor_thread):
                if (
                    thread is not None
                    and thread.is_alive()
                    and thread is not current_thread
                ):
                    thread.join(timeout=self.MONITOR_THREAD_JOIN_TIMEOUT_SECONDS)
            logger.info("bot.plugins.monitor.methods.monitoring.stop")
        else:
            logger.warning("bot.plugins.monitor.methods.monitoring.not.warn")

        if was_active:
            self.influxdb_client.shutdown_async_writes(wait=True)
            self.influxdb_client.close()
