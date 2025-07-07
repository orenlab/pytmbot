#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import platform
import time
from typing import Dict, Optional, Tuple, Final
from uuid import uuid4

import psutil

from pytmbot.logs import Logger
from pytmbot.plugins.monitor.models import ResourceMetrics, MonitoringState

logger = Logger()


class SystemMetrics:
    """Utility class for collecting system metrics."""

    __slots__ = ("sensors_available",)

    EXCLUDED_PARTITIONS: Final = frozenset(
        {
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
    )

    def __init__(self):
        self.sensors_available = True

    def collect_metrics(self) -> ResourceMetrics:
        """Collect all system metrics efficiently."""
        return {
            "cpu_usage": self._check_cpu_usage(),
            "memory_usage": self._check_memory_usage(),
            "disk_usage": self._get_disk_usage(),
            "temperatures": self._check_temperatures(),
            "fan_speeds": self._get_fan_speeds(),
            "load_averages": self._check_load_average(),
        }

    @staticmethod
    def _check_cpu_usage() -> float:
        try:
            return psutil.cpu_percent(interval=1)
        except Exception as e:
            logger.error(f"CPU usage check failed: {e}", exc_info=True)
            return 0.0

    @staticmethod
    def _check_memory_usage() -> float:
        try:
            return psutil.virtual_memory().percent
        except Exception as e:
            logger.error(f"Memory usage check failed: {e}", exc_info=True)
            return 0.0

    @staticmethod
    def _get_disk_usage() -> Dict[str, float]:
        try:
            return {
                partition.device: psutil.disk_usage(partition.mountpoint).percent
                for partition in psutil.disk_partitions(all=False)
                if not any(
                    excluded in partition.device
                    for excluded in SystemMetrics.EXCLUDED_PARTITIONS
                )
            }
        except Exception as e:
            logger.error(f"Disk usage check failed: {e}", exc_info=True)
            return {}

    def _check_temperatures(self) -> Dict[str, Dict[str, Optional[float]]]:
        try:
            temps = psutil.sensors_temperatures()
            if not temps and self.sensors_available:
                logger.warning("No temperature sensors available")
                self.sensors_available = False
                return {}

            return {
                f"{name}_{entry.label or 'default'}": {
                    "current": entry.current,
                    "high": entry.high,
                    "critical": entry.critical,
                }
                for name, entries in temps.items()
                for entry in entries
            }
        except Exception as e:
            logger.error(f"Temperature check failed: {e}", exc_info=True)
            return {}

    @staticmethod
    def _get_fan_speeds() -> Dict[str, Dict[str, int]]:
        try:
            return {
                f"{name}_{entry.label or 'default'}": {"current": entry.current}
                for name, entries in psutil.sensors_fans().items()
                for entry in entries
            }
        except Exception as e:
            logger.error(f"Fan speed check failed: {e}", exc_info=True)
            return {}

    @staticmethod
    def _check_load_average() -> Tuple[float, float, float]:
        try:
            if hasattr(psutil, "getloadavg"):
                return psutil.getloadavg()
            return 0.0, 0.0, 0.0
        except Exception as e:
            logger.error(f"Load average check failed: {e}", exc_info=True)
            return 0.0, 0.0, 0.0


class EventTracker:
    """Utility class for tracking system events."""

    __slots__ = ()

    @staticmethod
    def create_event(state: MonitoringState, event_type: str, details: dict) -> str:
        """Create a new event and return its ID."""
        event_id = str(uuid4())
        state.active_events[event_id] = {
            "id": event_id,
            "start_time": time.time(),
            "last_notification": time.time(),
            "type": event_type,
            "details": details,
            "resolved": False,
        }
        logger.info(
            f"New event created: {event_type}",
            extra={"event_id": event_id, "details": details},
        )
        return event_id

    @staticmethod
    def resolve_event(state: MonitoringState, event_id: str) -> Optional[float]:
        """Resolve an event and return its duration."""
        if event_id not in state.active_events:
            return None

        event = state.active_events[event_id]
        if event["resolved"]:
            return None

        duration = time.time() - event["start_time"]
        event["resolved"] = True

        logger.info(
            f"Event resolved: {event['type']}",
            extra={
                "event_id": event_id,
                "duration": duration,
                "details": event["details"],
            },
        )

        return duration


class SystemInfo:
    """Utility class for system information."""

    __slots__ = ()

    @staticmethod
    def get_platform_metadata(is_docker: bool) -> dict:
        try:
            uname = platform.uname()
            return {
                "system": "docker" if is_docker else "bare-metal",
                "hostname": uname.node,
                "platform": uname.system,
                "architecture": uname.machine,
                "python_version": platform.python_version(),
            }
        except Exception as e:
            logger.error(f"Failed to get platform metadata: {e}", exc_info=True)
            return {"system": "unknown", "hostname": "unknown"}
