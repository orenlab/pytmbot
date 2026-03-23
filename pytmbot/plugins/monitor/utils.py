#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import platform
import time
from typing import Final
from uuid import uuid4

import psutil

from pytmbot.adapters.psutil.adapter import PsutilAdapter
from pytmbot.logs import Logger
from pytmbot.plugins.monitor.models import MonitoringState, ResourceMetrics
from pytmbot.utils import to_float

logger = Logger()


class SystemMetrics:
    """Utility class for collecting system metrics."""

    __slots__ = (
        "sensors_available",
        "_psutil_adapter",
        "_has_getloadavg",
        "_disk_usage_cache",
        "_disk_usage_cached_at",
        "_temperatures_cache",
        "_temperatures_cached_at",
        "_fan_speeds_cache",
        "_fan_speeds_cached_at",
    )

    DISK_USAGE_CACHE_TTL_SECONDS: Final[float] = 10.0
    TEMPERATURES_CACHE_TTL_SECONDS: Final[float] = 15.0
    FAN_SPEEDS_CACHE_TTL_SECONDS: Final[float] = 15.0

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

    def __init__(self, psutil_adapter: PsutilAdapter | None = None) -> None:
        self.sensors_available = True
        self._psutil_adapter = psutil_adapter
        self._has_getloadavg = hasattr(psutil, "getloadavg")
        self._disk_usage_cache: dict[str, float] = {}
        self._disk_usage_cached_at = 0.0
        self._temperatures_cache: dict[str, dict[str, float | None]] = {}
        self._temperatures_cached_at = 0.0
        self._fan_speeds_cache: dict[str, dict[str, int]] = {}
        self._fan_speeds_cached_at = 0.0

    def collect_metrics(self, *, cpu_usage: float | None = None) -> ResourceMetrics:
        """Collect all system metrics efficiently."""
        resolved_cpu_usage = (
            self._check_cpu_usage() if cpu_usage is None else float(cpu_usage)
        )
        return {
            "cpu_usage": resolved_cpu_usage,
            "memory_usage": self._check_memory_usage(),
            "disk_usage": self._get_disk_usage(),
            "temperatures": self._check_temperatures(),
            "fan_speeds": self._get_fan_speeds(),
            "load_averages": self._check_load_average(),
        }

    def _check_cpu_usage(self) -> float:
        try:
            if self._psutil_adapter is not None:
                cpu_stats = self._psutil_adapter.get_cpu_usage()
                return to_float(cpu_stats.get("cpu_percent"), 0.0)
            # Non-blocking fallback when shared adapter is not available.
            return to_float(psutil.cpu_percent(interval=0.0), 0.0)
        except Exception:
            logger.error("bot.plugins.monitor.utils.cpu.usage.fail", exc_info=True)
            return 0.0

    def _check_memory_usage(self) -> float:
        try:
            return to_float(psutil.virtual_memory().percent, 0.0)
        except Exception:
            logger.error("bot.plugins.monitor.utils.memory.usage.fail", exc_info=True)
            return 0.0

    @staticmethod
    def _is_cache_valid(cached_at: float, ttl_seconds: float) -> bool:
        return cached_at > 0 and (time.monotonic() - cached_at) < ttl_seconds

    def _get_disk_usage(self) -> dict[str, float]:
        if self._is_cache_valid(
            self._disk_usage_cached_at, self.DISK_USAGE_CACHE_TTL_SECONDS
        ):
            return dict(self._disk_usage_cache)

        try:
            usage: dict[str, float] = {}
            for partition in psutil.disk_partitions(all=False):
                fstype = str(
                    getattr(partition, "fstype", getattr(partition, "device", ""))
                ).lower()
                if any(
                    excluded in fstype for excluded in SystemMetrics.EXCLUDED_PARTITIONS
                ):
                    continue

                device = str(getattr(partition, "device", ""))
                mountpoint = str(getattr(partition, "mountpoint", ""))
                if not mountpoint:
                    continue
                key = device or mountpoint
                usage[key] = psutil.disk_usage(mountpoint).percent
            self._disk_usage_cache = dict(usage)
            self._disk_usage_cached_at = time.monotonic()
            return usage
        except Exception:
            logger.error("bot.plugins.monitor.utils.disk.usage.fail", exc_info=True)
            return {}

    def _check_temperatures(self) -> dict[str, dict[str, float | None]]:
        if self._is_cache_valid(
            self._temperatures_cached_at, self.TEMPERATURES_CACHE_TTL_SECONDS
        ):
            return {
                sensor: dict(values)
                for sensor, values in self._temperatures_cache.items()
            }

        try:
            temps = psutil.sensors_temperatures()
            if not temps:
                if self.sensors_available:
                    logger.warning("bot.plugins.monitor.utils.no.temperature.warn")
                    self.sensors_available = False
                self._temperatures_cache = {}
                self._temperatures_cached_at = time.monotonic()
                return {}

            self.sensors_available = True
            result = {
                f"{name}_{entry.label or 'default'}": {
                    "current": entry.current,
                    "high": entry.high,
                    "critical": entry.critical,
                }
                for name, entries in temps.items()
                for entry in entries
            }
            self._temperatures_cache = {
                sensor: dict(values) for sensor, values in result.items()
            }
            self._temperatures_cached_at = time.monotonic()
            return result
        except Exception:
            logger.error(
                "bot.plugins.monitor.utils.temperature.check.fail", exc_info=True
            )
            return {}

    def _get_fan_speeds(self) -> dict[str, dict[str, int]]:
        if self._is_cache_valid(
            self._fan_speeds_cached_at, self.FAN_SPEEDS_CACHE_TTL_SECONDS
        ):
            return {
                sensor: dict(values)
                for sensor, values in self._fan_speeds_cache.items()
            }

        try:
            result = {
                f"{name}_{entry.label or 'default'}": {"current": entry.current}
                for name, entries in psutil.sensors_fans().items()
                for entry in entries
            }
            self._fan_speeds_cache = {
                sensor: dict(values) for sensor, values in result.items()
            }
            self._fan_speeds_cached_at = time.monotonic()
            return result
        except Exception:
            logger.error("bot.plugins.monitor.utils.fan.speed.fail", exc_info=True)
            return {}

    def _check_load_average(self) -> tuple[float, float, float]:
        try:
            if self._psutil_adapter is not None:
                load_avg = self._psutil_adapter.get_load_average()
            elif self._has_getloadavg:
                load_avg = psutil.getloadavg()
            else:
                return 0.0, 0.0, 0.0

            if (
                isinstance(load_avg, tuple)
                and len(load_avg) == 3
                and all(isinstance(value, (int, float)) for value in load_avg)
            ):
                return (
                    float(load_avg[0]),
                    float(load_avg[1]),
                    float(load_avg[2]),
                )
            return 0.0, 0.0, 0.0
        except Exception:
            logger.error("bot.plugins.monitor.utils.load.average.fail", exc_info=True)
            return 0.0, 0.0, 0.0


class EventTracker:
    """Utility class for tracking system events."""

    __slots__ = ()

    @staticmethod
    def create_event(
        state: MonitoringState, event_type: str, details: dict[str, object]
    ) -> str:
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
            "bot.plugins.monitor.utils.event.create.info",
            extra={"event_id": event_id, "details": details},
        )
        return event_id

    @staticmethod
    def resolve_event(state: MonitoringState, event_id: str) -> float | None:
        """Resolve an event and return its duration."""
        if event_id not in state.active_events:
            return None

        event = state.active_events[event_id]
        if event["resolved"]:
            return None

        duration = time.time() - event["start_time"]
        event["resolved"] = True

        logger.info(
            "bot.plugins.monitor.utils.event.resolved.info",
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
    def get_platform_metadata(is_docker: bool) -> dict[str, object]:
        try:
            uname = platform.uname()
            return {
                "system": "docker" if is_docker else "bare-metal",
                "hostname": uname.node,
                "platform": uname.system,
                "architecture": uname.machine,
                "python_version": platform.python_version(),
            }
        except Exception:
            logger.error("bot.plugins.monitor.utils.get.platform.fail", exc_info=True)
            return {"system": "unknown", "hostname": "unknown"}
