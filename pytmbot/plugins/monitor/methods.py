#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Literal

import psutil
from telebot import TeleBot

from pytmbot.adapters.docker.containers_info import (
    fetch_docker_counters,
    retrieve_containers_stats,
)
from pytmbot.adapters.docker.images_info import fetch_image_details
from pytmbot.adapters.psutil.adapter import PsutilAdapter
from pytmbot.adapters.psutil.adapter_types import TopProcess
from pytmbot.db.influxdb_interface import InfluxDBConfig, InfluxDBInterface
from pytmbot.logs import Logger
from pytmbot.plugins.monitor.models import ResourceThresholds
from pytmbot.plugins.monitor.utils import (
    EventTracker,
    MonitoringState,
    SystemInfo,
    SystemMetrics,
)
from pytmbot.plugins.plugins_core import PluginCore
from pytmbot.utils import is_running_in_docker, set_naturalsize

logger = Logger()


class SystemMonitorPlugin(PluginCore):
    """Plugin for monitoring system resources."""

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
        "poll_interval",
        "docker_counters_update_interval",
        "system_metrics",
        "_monitor_thread",
        "_supervisor_thread",
        "_monitor_thread_lock",
        "_monitor_restart_count",
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
        self._previous_container_hashes: dict[str, dict] = {}
        self._previous_image_hashes: dict[str, dict] = {}
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

        # Set monitoring intervals
        self.check_interval = self.monitor_settings.check_interval[0]
        self.poll_interval = 10 * 60  # 10 minutes
        self.docker_counters_update_interval = 5 * 60  # 5 minutes

        self.system_metrics = SystemMetrics()
        self._monitor_thread: threading.Thread | None = None
        self._supervisor_thread: threading.Thread | None = None
        self._monitor_thread_lock = threading.RLock()
        self._monitor_restart_count = 0

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

        self.state.is_active = True
        self._monitor_restart_count = 0

        retry_attempts = self.monitor_settings.retry_attempts[0]
        retry_interval = max(1, self.monitor_settings.retry_interval[0])

        for attempt in range(retry_attempts):
            try:
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
                        "event_threshold_duration": {self.event_threshold_duration},
                        "check_interval": self.check_interval,
                        "poll_interval": self.poll_interval,
                        "docker_counters_update_interval": self.docker_counters_update_interval,
                        "is_docker": self.is_docker,
                    }
                ) as log:
                    log.info("bot.plugins.monitor.methods.monitoring.start")
                return
            except Exception as e:
                logger.error("bot.plugins.monitor.methods.monitoring.start.fail", e)
                if attempt < retry_attempts - 1:
                    time.sleep(retry_interval)
                else:
                    self.state.is_active = False
                    raise RuntimeError(
                        "Failed to start monitoring after maximum attempts"
                    )

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
            time.sleep(retry_interval)

    def _monitor_system(self) -> None:
        while self.state.is_active:
            try:
                self._adjust_check_interval()

                # Collect and process metrics
                metrics: dict[str, Any] = dict(self.system_metrics.collect_metrics())
                if self.monitor_settings.monitor_docker:
                    self._process_docker_metrics(metrics)

                # Record metrics and process alerts
                self._record_metrics(metrics)
                self._process_alerts(metrics)

                time.sleep(self.check_interval)

            except Exception as e:
                logger.error("bot.plugins.monitor.methods.monitoring.cycle.fail", e)
                time.sleep(max(1, self.check_interval // 2))

    def _process_alerts(self, metrics: dict[str, Any]) -> None:
        self._check_cpu_alert(metrics["cpu_usage"])
        self._check_memory_alert(metrics["memory_usage"])
        self._check_temperature_alerts(metrics["temperatures"])
        self._check_disk_alerts(metrics["disk_usage"])

    def _check_cpu_alert(self, usage: float) -> None:
        if usage > self.thresholds.cpu_usage:
            event_id = next(
                (
                    eid
                    for eid, event in self.state.active_events.items()
                    if event["type"] == "cpu_usage" and not event["resolved"]
                ),
                None,
            )

            if not event_id:
                event_id = EventTracker.create_event(
                    self.state, "cpu_usage", {"usage": usage}
                )
                self._send_notification(self._format_cpu_alert(event_id, usage))
        else:
            for eid, event in list(self.state.active_events.items()):
                if event["type"] == "cpu_usage" and not event["resolved"]:
                    duration = EventTracker.resolve_event(self.state, eid)
                    if duration:
                        self._send_resolution_notification("CPU usage", duration)

    def _check_memory_alert(self, usage: float) -> None:
        if usage > self.thresholds.memory_usage:
            event_id = next(
                (
                    eid
                    for eid, event in self.state.active_events.items()
                    if event["type"] == "memory_usage" and not event["resolved"]
                ),
                None,
            )

            if not event_id:
                event_id = EventTracker.create_event(
                    self.state, "memory_usage", {"usage": usage}
                )
                self._send_notification(self._format_memory_alert(event_id, usage))
        else:
            for eid, event in list(self.state.active_events.items()):
                if event["type"] == "memory_usage" and not event["resolved"]:
                    duration = EventTracker.resolve_event(self.state, eid)
                    if duration:
                        self._send_resolution_notification("Memory usage", duration)

    def _check_temperature_alerts(self, temperatures: dict) -> None:
        for sensor, data in temperatures.items():
            threshold = getattr(self.thresholds, f"{sensor}_temp", 80.0)
            if data["current"] > threshold:
                event_id = next(
                    (
                        eid
                        for eid, event in self.state.active_events.items()
                        if event["type"] == f"temp_{sensor}" and not event["resolved"]
                    ),
                    None,
                )

                if not event_id:
                    event_id = EventTracker.create_event(
                        self.state,
                        f"temp_{sensor}",
                        {"temperature": data["current"], "sensor": sensor},
                    )
                    self._send_notification(
                        self._format_temperature_alert(event_id, sensor, data)
                    )
            else:
                for eid, event in list(self.state.active_events.items()):
                    if event["type"] == f"temp_{sensor}" and not event["resolved"]:
                        duration = EventTracker.resolve_event(self.state, eid)
                        if duration:
                            self._send_resolution_notification(
                                f"Temperature ({sensor})", duration
                            )

    def _check_disk_alerts(self, disk_usage: dict[str, float]) -> None:
        for disk, usage in disk_usage.items():
            if usage > self.thresholds.disk_usage:
                event_id = next(
                    (
                        eid
                        for eid, event in self.state.active_events.items()
                        if event["type"] == f"disk_{disk}" and not event["resolved"]
                    ),
                    None,
                )

                if not event_id:
                    event_id = EventTracker.create_event(
                        self.state, f"disk_{disk}", {"usage": usage, "disk": disk}
                    )
                    self._send_notification(
                        self._format_disk_alert(event_id, disk, usage)
                    )
            else:
                for eid, event in list(self.state.active_events.items()):
                    if event["type"] == f"disk_{disk}" and not event["resolved"]:
                        duration = EventTracker.resolve_event(self.state, eid)
                        if duration:
                            self._send_resolution_notification(
                                f"Disk usage ({disk})", duration
                            )

    def _process_docker_metrics(self, metrics: dict[str, Any]) -> None:
        current_time = time.time()
        if (
            current_time - self.state.docker_counters_last_updated
            >= self.docker_counters_update_interval
        ):
            try:
                new_counts = fetch_docker_counters()
                new_containers = retrieve_containers_stats()
                new_images = fetch_image_details()

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
        new_containers: list[dict[str, Any]],
        new_images: list[dict[str, Any]],
    ) -> None:
        try:
            new_container_hashes = {cont["id"]: cont for cont in new_containers}
            new_image_hashes = {img["id"]: img for img in new_images}

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

    def _record_metrics(self, fields: dict[str, Any]) -> None:
        try:
            metadata = SystemInfo.get_platform_metadata(self.is_docker)
            sanitized_fields = self._sanitize_fields(fields)

            with self.influxdb_client as client:
                client.write_data("system_metrics", sanitized_fields, metadata)

            logger.debug(
                "bot.plugins.monitor.methods.metrics.recorded.ok", extra=fields
            )
        except Exception:
            logger.exception("bot.plugins.monitor.methods.writing.metrics.fail")

    @staticmethod
    def _sanitize_fields(fields: dict[str, Any]) -> dict[str, Any]:
        sanitized_fields: dict[str, Any] = {}
        for key, value in fields.items():
            if isinstance(value, (int, float, str, bool, type(None))):
                sanitized_fields[key] = value
                continue

            if isinstance(value, dict):
                sanitized_fields.update(
                    {
                        f"{key}_{sub_key}": sub_value
                        for sub_key, sub_value in value.items()
                        if isinstance(sub_value, (int, float))
                    }
                )
                unsupported = {
                    sub_key: sub_value
                    for sub_key, sub_value in value.items()
                    if not isinstance(sub_value, (int, float))
                }
                for _sub_key, _sub_value in unsupported.items():
                    logger.warning("bot.plugins.monitor.methods.unsupported.type.warn")
                continue

            if isinstance(value, tuple):
                sanitized_fields.update(
                    {
                        f"{key}_{i + 1}m": item
                        for i, item in enumerate(value)
                        if isinstance(item, (int, float))
                    }
                )
                unsupported_tuple_items = [
                    (i, item)
                    for i, item in enumerate(value)
                    if not isinstance(item, (int, float))
                ]
                for _i, _item in unsupported_tuple_items:
                    logger.warning("bot.plugins.monitor.methods.unsupported.type.warn")
                continue

            logger.warning("bot.plugins.monitor.methods.unsupported.type.warn")
        return sanitized_fields

    def _send_notification(self, message: str) -> None:
        current_time = time.time()
        self._maybe_reset_notification_budget(current_time)

        if self.state.notification_count >= self.monitor_settings.max_notifications[0]:
            if not self.state.max_notifications_reached:
                logger.warning("bot.plugins.monitor.methods.maximum.notifications.warn")
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

            self.state.notification_count += 1
            self.state.next_notification_reset_at = (
                current_time + self._get_notification_reset_window_seconds()
            )

        except Exception as e:
            logger.error("bot.plugins.monitor.methods.send.notification.fail", e)

    def _get_notification_reset_window_seconds(self) -> int:
        """Resolve notification reset window from settings with safe fallback."""
        reset_window = self.monitor_settings.reset_notification_count[0]
        if isinstance(reset_window, int) and reset_window > 0:
            return reset_window
        return 300

    def _maybe_reset_notification_budget(
        self, current_time: float | None = None
    ) -> None:
        """Reset notification counters lazily when reset deadline has passed."""
        now = current_time if current_time is not None else time.time()
        next_reset_at = self.state.next_notification_reset_at
        if next_reset_at > 0 and now >= next_reset_at:
            self._reset_notification_count()
            self.state.next_notification_reset_at = 0.0

    @staticmethod
    def _format_cpu_alert(event_id: str, usage: float) -> str:
        """
        Format CPU alert message with top processes information.

        Args:
            event_id: Unique identifier for the alert event
            usage: Current CPU usage percentage

        Returns:
            Formatted alert message with top processes
        """
        adapter = PsutilAdapter()
        top_processes = adapter.get_top_processes(count=5)
        process_info = "\n".join(
            f"  • {proc['name']} (PID: {proc['pid']}) - {proc['cpu_percent']:.1f}% CPU"
            for proc in sorted(
                top_processes, key=lambda x: x["cpu_percent"], reverse=True
            )
        )

        return (
            f"🔥 <b>High CPU Usage Alert!</b> 🔥\n"
            f"Event ID: {event_id}\n"
            f"Current Usage: {usage:.1f}%\n\n"
            f"<b>Top CPU Consuming Processes:</b>\n"
            f"{process_info}"
        )

    @staticmethod
    def _format_memory_alert(event_id: str, usage: float) -> str:
        """
        Format memory alert message with top processes information.

        Args:
            event_id: Unique identifier for the alert event
            usage: Current memory usage percentage

        Returns:
            Formatted alert message with top processes
        """
        adapter = PsutilAdapter()
        top_processes = adapter.get_top_processes(count=5)
        process_info = "\n".join(
            f"  • {proc['name']} (PID: {proc['pid']}) - {proc['memory_percent']:.1f}% MEM"
            for proc in sorted(
                top_processes, key=lambda x: x["memory_percent"], reverse=True
            )
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
        return "\n".join(
            f"  • {proc['name']} (PID: {proc['pid']}) - "
            f"{proc[resource_key]:.1f}{suffix}"
            for proc in sorted(processes, key=lambda x: x[resource_key], reverse=True)
        )

    @staticmethod
    def _format_temperature_alert(event_id: str, sensor: str, data: dict) -> str:
        return (
            f"🌡️ <b>High Temperature Alert - {sensor}</b>\n"
            f"Event ID: {event_id}\n"
            f"Current: {data['current']:.1f}°C"
        )

    @staticmethod
    def _format_disk_alert(event_id: str, disk: str, usage: float) -> str:
        return (
            f"💽 <b>High Disk Usage Alert - {disk}</b>\n"
            f"Event ID: {event_id}\n"
            f"Current Usage: {usage:.1f}%"
        )

    def _send_container_notification(self, container: dict) -> None:
        message = (
            "🚨 <b>Security Alert: New Docker Container Detected</b> 🚨\n"
            f"📦 <b>Name:</b> <i>{container['name']}</i>\n"
            f"🖼️ <b>Image:</b> <i>{container['image']}</i>\n"
            f"🕒 <b>Created:</b> <i>{container['created']}</i>\n"
            f"🚀 <b>Running Since:</b> <i>{container['run_at']}</i>\n"
            f"📊 <b>Status:</b> <i>{container['status']}</i>\n"
            f"🔍 <b>Networks:</b> <i>{container.get('networks', 'N/A')}</i>\n"
            f"🔌 <b>Ports:</b> <i>{container.get('ports', 'N/A')}</i>\n"
            "⚠️ Please verify this container's authenticity and permissions."
        )
        self._send_notification(message)

    def _send_image_notification(self, image: dict) -> None:
        message = (
            "🚨 <b>Security Alert: New Docker Image Detected</b> 🚨\n"
            f"🖼️ <b>ID:</b> <i>{image['id'][:12]}</i>\n"
            f"🏷️ <b>Tags:</b> <i>{', '.join(image['tags']) or 'None'}</i>\n"
            f"🔧 <b>Architecture:</b> <i>{image['architecture']}</i>\n"
            f"💻 <b>OS:</b> <i>{image['os']}</i>\n"
            f"📦 <b>Size:</b> <i>{set_naturalsize(image['size'])}</i>\n"
            f"🕒 <b>Created:</b> <i>{image['created']}</i>\n"
            "⚠️ Please verify this image's authenticity and source."
        )
        self._send_notification(message)

    def _send_resolution_notification(self, event_type: str, duration: float) -> None:
        message = (
            f"✅ <b>{event_type} has normalized</b>\nDuration: {int(duration)} seconds"
        )
        self._send_notification(message)

    def _reset_notification_count(self) -> None:
        self.state.notification_count = 0
        self.state.max_notifications_reached = False
        logger.debug("bot.plugins.monitor.methods.notification.counter.debug")

    def _adjust_check_interval(self) -> None:
        try:
            cpu_load = psutil.cpu_percent(interval=0.0)
            if cpu_load > self.thresholds.load:
                new_interval = min(self.check_interval * 2, 30)
                if new_interval != self.check_interval:
                    self.check_interval = new_interval
                    logger.info(
                        "bot.plugins.monitor.methods.check.interval.info",
                        extra={"cpu_load": cpu_load, "new_interval": new_interval},
                    )
            else:
                self.check_interval = self.monitor_settings.check_interval[0]
        except Exception as e:
            logger.error("bot.plugins.monitor.methods.adjust.check.fail", e)

    def stop_monitoring(self) -> None:
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
                    thread.join(timeout=2)
            logger.info("bot.plugins.monitor.methods.monitoring.stop")
        else:
            logger.warning("bot.plugins.monitor.methods.monitoring.not.warn")
