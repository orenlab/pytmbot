from __future__ import annotations

import threading
import time
from typing import Dict

import psutil
from telebot import TeleBot

from pytmbot.adapters.docker.containers_info import (
    fetch_docker_counters,
    retrieve_containers_stats,
)
from pytmbot.adapters.docker.images_info import fetch_image_details
from pytmbot.db.influxdb_interface import InfluxDBInterface, InfluxDBConfig
from pytmbot.logs import Logger
from pytmbot.plugins.monitor.models import ResourceThresholds
from pytmbot.plugins.monitor.utils import (
    MonitoringState, SystemMetrics,
    EventTracker, SystemInfo
)
from pytmbot.plugins.plugins_core import PluginCore
from pytmbot.settings import settings
from pytmbot.utils.utilities import is_running_in_docker, set_naturalsize

logger = Logger()


class SystemMonitorPlugin(PluginCore):
    """Optimized plugin for monitoring system resources."""

    __slots__ = (
        'bot', 'monitor_settings', 'event_threshold_duration',
        'state', 'thresholds', '_previous_container_hashes',
        '_previous_image_hashes', '_previous_counts', '_known_container_ids',
        '_known_image_ids', 'influxdb_client', 'is_docker', 'check_interval',
        'poll_interval', 'docker_counters_update_interval', 'system_metrics'
    )

    def __init__(
            self,
            bot: TeleBot,
            event_threshold_duration: float = 20
    ) -> None:
        super().__init__()

        self.bot = bot
        self.monitor_settings = self.settings.plugins_config.monitor
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
            disk_usage=self.monitor_settings.tracehold.disk_usage_threshold[0]
        )

        # Docker monitoring state
        self._previous_container_hashes: Dict[str, dict] = {}
        self._previous_image_hashes: Dict[str, dict] = {}
        self._previous_counts: Dict[str, int] = {
            "containers_count": 0,
            "images_count": 0
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

    def _init_influxdb(self) -> None:
        try:
            self.influxdb_client = InfluxDBInterface(
                InfluxDBConfig(
                    url=settings.influxdb.url[0].get_secret_value(),
                    token=settings.influxdb.token[0].get_secret_value(),
                    org=settings.influxdb.org[0].get_secret_value(),
                    bucket=settings.influxdb.bucket[0].get_secret_value(),
                    debug_mode=settings.influxdb.debug_mode
                )
            )
        except Exception as e:
            logger.error("Failed to initialize InfluxDB client", e)
            raise

    def start_monitoring(self) -> None:
        if not self.state.is_active:
            self.state.is_active = True
            retry_attempts = self.monitor_settings.retry_attempts[0]
            retry_interval = self.monitor_settings.retry_interval[0]

            for attempt in range(retry_attempts):
                try:
                    thread = threading.Thread(
                        target=self._monitor_system,
                        name="SystemMonitorThread",
                        daemon=True
                    )
                    thread.start()
                    with logger.context(
                            context={
                                "component": "monitoring",
                                "action": "start",
                                "attempt": attempt,
                                "trace hold": self.monitor_settings.tracehold,
                                "event_threshold_duration": {self.event_threshold_duration},
                                "check_interval": self.check_interval,
                                "poll_interval": self.poll_interval,
                                "docker_counters_update_interval": self.docker_counters_update_interval,
                                "is_docker": self.is_docker
                            }
                    ) as log:
                        log.info("Monitoring started successfully")
                    return
                except Exception as e:
                    logger.error(
                        f"Monitoring start attempt {attempt + 1} failed",
                        e
                    )
                    if attempt < retry_attempts - 1:
                        time.sleep(retry_interval)
                    else:
                        self.state.is_active = False
                        raise RuntimeError(
                            "Failed to start monitoring after maximum attempts"
                        )

    def _monitor_system(self) -> None:
        while self.state.is_active:
            try:
                self._adjust_check_interval()

                # Collect and process metrics
                metrics = self.system_metrics.collect_metrics()
                if self.monitor_settings.monitor_docker:
                    self._process_docker_metrics(metrics)

                # Record metrics and process alerts
                self._record_metrics(metrics)
                self._process_alerts(metrics)

                time.sleep(self.check_interval)

            except Exception as e:
                logger.error("Monitoring cycle failed", e)
                time.sleep(max(1, self.check_interval // 2))

    def _process_alerts(self, metrics: dict) -> None:
        self._check_cpu_alert(metrics['cpu_usage'])
        self._check_memory_alert(metrics['memory_usage'])
        self._check_temperature_alerts(metrics['temperatures'])
        self._check_disk_alerts(metrics['disk_usage'])

    def _check_cpu_alert(self, usage: float) -> None:
        if usage > self.thresholds.cpu_usage:
            event_id = next(
                (eid for eid, event in self.state.active_events.items()
                 if event['type'] == 'cpu_usage' and not event['resolved']),
                None
            )

            if not event_id:
                event_id = EventTracker.create_event(
                    self.state,
                    'cpu_usage',
                    {'usage': usage}
                )
                self._send_notification(self._format_cpu_alert(event_id, usage))
        else:
            for eid, event in list(self.state.active_events.items()):
                if event['type'] == 'cpu_usage' and not event['resolved']:
                    duration = EventTracker.resolve_event(self.state, eid)
                    if duration:
                        self._send_resolution_notification('CPU usage', duration)

    def _check_memory_alert(self, usage: float) -> None:
        if usage > self.thresholds.memory_usage:
            event_id = next(
                (eid for eid, event in self.state.active_events.items()
                 if event['type'] == 'memory_usage' and not event['resolved']),
                None
            )

            if not event_id:
                event_id = EventTracker.create_event(
                    self.state,
                    'memory_usage',
                    {'usage': usage}
                )
                self._send_notification(self._format_memory_alert(event_id, usage))
        else:
            for eid, event in list(self.state.active_events.items()):
                if event['type'] == 'memory_usage' and not event['resolved']:
                    duration = EventTracker.resolve_event(self.state, eid)
                    if duration:
                        self._send_resolution_notification('Memory usage', duration)

    def _check_temperature_alerts(self, temperatures: dict) -> None:
        for sensor, data in temperatures.items():
            threshold = getattr(self.thresholds, f"{sensor}_temp", 80.0)
            if data['current'] > threshold:
                event_id = next(
                    (eid for eid, event in self.state.active_events.items()
                     if event['type'] == f'temp_{sensor}' and not event['resolved']),
                    None
                )

                if not event_id:
                    event_id = EventTracker.create_event(
                        self.state,
                        f'temp_{sensor}',
                        {'temperature': data['current'], 'sensor': sensor}
                    )
                    self._send_notification(
                        self._format_temperature_alert(event_id, sensor, data)
                    )
            else:
                for eid, event in list(self.state.active_events.items()):
                    if (event['type'] == f'temp_{sensor}' and
                            not event['resolved']):
                        duration = EventTracker.resolve_event(self.state, eid)
                        if duration:
                            self._send_resolution_notification(
                                f'Temperature ({sensor})',
                                duration
                            )

    def _check_disk_alerts(self, disk_usage: Dict[str, float]) -> None:
        for disk, usage in disk_usage.items():
            if usage > self.thresholds.disk_usage:
                event_id = next(
                    (eid for eid, event in self.state.active_events.items()
                     if event['type'] == f'disk_{disk}' and not event['resolved']),
                    None
                )

                if not event_id:
                    event_id = EventTracker.create_event(
                        self.state,
                        f'disk_{disk}',
                        {'usage': usage, 'disk': disk}
                    )
                    self._send_notification(
                        self._format_disk_alert(event_id, disk, usage)
                    )
            else:
                for eid, event in list(self.state.active_events.items()):
                    if event['type'] == f'disk_{disk}' and not event['resolved']:
                        duration = EventTracker.resolve_event(self.state, eid)
                        if duration:
                            self._send_resolution_notification(
                                f'Disk usage ({disk})',
                                duration
                            )

    def _process_docker_metrics(self, metrics: dict) -> None:
        current_time = time.time()
        if (current_time - self.state.docker_counters_last_updated
                >= self.docker_counters_update_interval):
            try:
                new_counts = fetch_docker_counters()
                new_containers = retrieve_containers_stats()
                new_images = fetch_image_details()

                self._detect_docker_changes(new_counts, new_containers, new_images)
                self.state.docker_counters_last_updated = current_time

                metrics.update({
                    f"docker_{key}": value
                    for key, value in new_counts.items()
                })

            except Exception as e:
                logger.error("Docker metrics processing failed", e)

    def _detect_docker_changes(
            self,
            new_counts: dict,
            new_containers: list,
            new_images: list
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
                    "Docker monitoring initialized",
                    extra={
                        "containers": len(new_container_hashes),
                        "images": len(new_image_hashes)
                    }
                )
            else:
                # Check for genuinely new containers (not seen before)
                new_container_ids = set(new_container_hashes.keys()) - self._known_container_ids
                for container_id in new_container_ids:
                    self._send_container_notification(new_container_hashes[container_id])
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
            logger.error("Failed to detect Docker changes", e)

    def _record_metrics(self, fields: dict) -> None:
        try:
            metadata = SystemInfo.get_platform_metadata(self.is_docker)
            sanitized_fields = self._sanitize_fields(fields)

            with self.influxdb_client as client:
                client.write_data("system_metrics", sanitized_fields, metadata)

            logger.debug("Metrics recorded successfully", extra=fields)
        except Exception as e:
            logger.exception(f"Error writing metrics to InfluxDB: {e}")

    @staticmethod
    def _sanitize_fields(fields: dict) -> dict:
        sanitized_fields = {}
        for key, value in fields.items():
            if isinstance(value, (int, float, str, bool, type(None))):
                sanitized_fields[key] = value
                continue

            if isinstance(value, dict):
                sanitized_fields.update({
                    f"{key}_{sub_key}": sub_value
                    for sub_key, sub_value in value.items()
                    if isinstance(sub_value, (int, float))
                })
                unsupported = {sub_key: sub_value for sub_key, sub_value in value.items() if
                               not isinstance(sub_value, (int, float))}
                for sub_key, sub_value in unsupported.items():
                    logger.warning(f"Unsupported type for nested field '{key}_{sub_key}': {type(sub_value)}")
                continue

            if isinstance(value, tuple):
                sanitized_fields.update({
                    f"{key}_{i + 1}m": item
                    for i, item in enumerate(value)
                    if isinstance(item, (int, float))
                })
                unsupported = [(i, item) for i, item in enumerate(value) if not isinstance(item, (int, float))]
                for i, item in unsupported:
                    logger.warning(f"Unsupported type for tuple element '{key}_{i}': {type(item)}")
                continue

            logger.warning(f"Unsupported type for field '{key}': {type(value)}")
        return sanitized_fields

    def _send_notification(self, message: str) -> None:
        if self.state.notification_count >= self.monitor_settings.max_notifications[0]:
            if not self.state.max_notifications_reached:
                logger.warning("Maximum notifications reached")
                self.state.max_notifications_reached = True
            return

        try:
            self.bot.send_message(
                self.settings.chat_id.global_chat_id[0],
                message,
                parse_mode="HTML"
            )
            logger.info("Notification sent", extra={"message": str(message)})

            self.state.notification_count += 1
            self._schedule_notification_reset()

        except Exception as e:
            logger.error("Failed to send notification", e)

    @staticmethod
    def _format_cpu_alert(event_id: str, usage: float) -> str:
        return (
            f"🔥 <b>High CPU Usage Alert!</b> 🔥\n"
            f"Event ID: {event_id}\n"
            f"Current Usage: {usage:.1f}%"
        )

    @staticmethod
    def _format_memory_alert(event_id: str, usage: float) -> str:
        return (
            f"🧠 <b>High Memory Usage Alert!</b> 🧠\n"
            f"Event ID: {event_id}\n"
            f"Current Usage: {usage:.1f}%"
        )

    @staticmethod
    def _format_temperature_alert(
            event_id: str,
            sensor: str,
            data: dict
    ) -> str:
        return (
            f"🌡️ <b>High Temperature Alert - {sensor}</b>\n"
            f"Event ID: {event_id}\n"
            f"Current: {data['current']:.1f}°C"
        )

    @staticmethod
    def _format_disk_alert(
            event_id: str,
            disk: str,
            usage: float
    ) -> str:
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

    def _send_resolution_notification(
            self,
            event_type: str,
            duration: float
    ) -> None:
        message = (
            f"✅ <b>{event_type} has normalized</b>\n"
            f"Duration: {int(duration)} seconds"
        )
        self._send_notification(message)

    def _schedule_notification_reset(self) -> None:
        try:
            reset_thread = threading.Timer(
                300,  # 5 minutes
                self._reset_notification_count
            )
            reset_thread.daemon = True
            reset_thread.start()
        except Exception as e:
            logger.error("Failed to schedule notification reset", e)

    def _reset_notification_count(self) -> None:
        self.state.notification_count = 0
        self.state.max_notifications_reached = False
        logger.debug("Notification counter reset")

    def _adjust_check_interval(self) -> None:
        try:
            cpu_load = psutil.cpu_percent(interval=1)
            if cpu_load > self.thresholds.load:
                new_interval = min(self.check_interval * 2, 30)
                if new_interval != self.check_interval:
                    self.check_interval = new_interval
                    logger.info(
                        "Check interval adjusted",
                        extra={
                            "cpu_load": cpu_load,
                            "new_interval": new_interval
                        }
                    )
            else:
                self.check_interval = self.monitor_settings.check_interval[0]
        except Exception as e:
            logger.error("Failed to adjust check interval", e)

    def stop_monitoring(self) -> None:
        if self.state.is_active:
            self.state.is_active = False
            logger.info("System monitoring stopped")
        else:
            logger.warning("Monitoring is not running")
