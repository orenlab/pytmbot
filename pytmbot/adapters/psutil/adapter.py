#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import concurrent
import concurrent.futures
import os
from contextlib import suppress
from datetime import datetime
from typing import Optional, Dict, Any, Callable

import psutil

from pytmbot.adapters.psutil.adapter_types import (
    LoadAverage,
    MemoryStats,
    DiskStats,
    SwapStats,
    SensorStats,
    ProcessStats,
    NetworkIOStats,
    UserInfo,
    NetworkInterfaceStats,
    CPUFrequencyStats,
    CPUUsageStats,
    TopProcess,
)
from pytmbot.logs import Logger
from pytmbot.utils import set_naturalsize

logger = Logger()


class PsutilAdapter:
    """Provides system statistics using psutil with advanced error handling."""

    def __init__(self) -> None:
        self._psutil = psutil

    @staticmethod
    def _safe_execute(operation: str, func, fallback, **log_context) -> any:
        """Execute operations safely with proper logging and error handling."""
        try:
            logger.debug(f"Retrieving {operation}", extra=log_context)
            result = func()
            logger.debug(
                f"Successfully retrieved {operation}",
                extra={"result": result, **log_context},
            )
            return result
        except Exception as e:
            logger.error(
                f"Failed to retrieve {operation}",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "operation": operation,
                    **log_context,
                },
            )
            return fallback

    def get_process_stats(self, pid: Optional[int] = None) -> Dict[str, Any]:
        """
        Get comprehensive statistics for a specific process.

        Args:
            pid: Process ID. If None, uses current process.

        Returns:
            Dictionary with process statistics including CPU, memory, IO, etc.
        """

        if pid is not None and (not isinstance(pid, int) or pid <= 0):
            raise ValueError("PID must be a positive integer")

        def _get_process_info():
            try:
                process = self._psutil.Process(pid) if pid else self._psutil.Process()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return {}

            # Collect stats using concurrent execution for better performance
            stats_collectors = [
                ("basic_info", lambda: self._get_basic_process_info(process)),
                ("cpu_stats", lambda: self._get_process_cpu_stats(process)),
                ("memory_stats", lambda: self._get_process_memory_stats(process)),
                ("io_stats", lambda: self._get_process_io_stats(process)),
                ("file_stats", lambda: self._get_process_file_stats(process)),
                ("network_stats", lambda: self._get_process_network_stats(process)),
                ("context_stats", lambda: self._get_process_context_stats(process)),
                ("path_stats", lambda: self._get_process_path_stats(process)),
            ]

            return self._collect_stats_concurrently(stats_collectors)

        return self._safe_execute(
            f"process stats (PID: {pid or os.getpid()})",
            _get_process_info,
            {},
            pid=pid or os.getpid(),
        )

    @staticmethod
    def _collect_stats_concurrently(
        collectors: list[tuple[str, Callable]],
    ) -> Dict[str, Any]:
        """
        Collect statistics concurrently using ThreadPoolExecutor.

        Args:
            collectors: List of (name, collector_function) tuples

        Returns:
            Merged dictionary of all collected statistics
        """
        final_stats = {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            # Submit all tasks
            future_to_name = {
                executor.submit(collector): name for name, collector in collectors
            }

            # Collect results as they complete
            for future in concurrent.futures.as_completed(future_to_name):
                name = future_to_name[future]
                try:
                    stats = future.result(timeout=2.0)  # 2 second timeout per operation
                    if stats:  # Only update if we got valid stats
                        final_stats.update(stats)
                except Exception as e:
                    logger.warning(
                        f"Failed to collect {name} stats",
                        extra={"error": str(e), "collector": name},
                    )

        return final_stats

    def _get_basic_process_info(self, process) -> Dict[str, Any]:
        """Get basic process information with safe execution."""
        return self._safe_execute(
            "basic process info",
            lambda: {
                "pid": process.pid,
                "name": process.name(),
                "status": process.status(),
                "create_time": process.create_time(),
            },
            {},
        )

    def _get_process_cpu_stats(self, process) -> Dict[str, Any]:
        """Get CPU-related process statistics with safe execution."""

        def _collect_cpu_stats():
            cpu_percent = process.cpu_percent(interval=0.1)
            return {
                "cpu_percent": f"{cpu_percent:.1f}%",
                "cpu_times": process.cpu_times()._asdict(),
                "cpu_num": getattr(process, "cpu_num", lambda: None)(),
            }

        return self._safe_execute("CPU stats", _collect_cpu_stats, {})

    def _get_process_memory_stats(self, process) -> Dict[str, Any]:
        """Get memory-related process statistics with safe execution."""

        def _collect_memory_stats():
            memory_info = process.memory_info()
            memory_percent = process.memory_percent()

            stats = {
                "memory_rss": set_naturalsize(memory_info.rss),
                "memory_vms": set_naturalsize(memory_info.vms),
                "memory_percent": f"{memory_percent:.1f}%",
            }

            # Extended memory info if available
            if hasattr(process, "memory_full_info"):
                try:
                    full_memory = process.memory_full_info()
                    stats.update(
                        {
                            "memory_uss": set_naturalsize(full_memory.uss),
                            "memory_pss": set_naturalsize(full_memory.pss),
                        }
                    )
                except (AttributeError, psutil.AccessDenied):
                    pass

            return stats

        return self._safe_execute("memory stats", _collect_memory_stats, {})

    def _get_process_io_stats(self, process) -> Dict[str, Any]:
        """Get I/O statistics for the process with safe execution."""

        def _collect_io_stats():
            io_counters = process.io_counters()
            return {
                "io_read_count": io_counters.read_count,
                "io_write_count": io_counters.write_count,
                "io_read_bytes": set_naturalsize(io_counters.read_bytes),
                "io_write_bytes": set_naturalsize(io_counters.write_bytes),
            }

        return self._safe_execute("I/O stats", _collect_io_stats, {})

    def _get_process_file_stats(self, process) -> Dict[str, Any]:
        """Get file descriptor and thread statistics with safe execution."""

        def _collect_file_stats():
            return {
                "num_fds": (
                    process.num_fds() if hasattr(process, "num_fds") else "N/A"
                ),
                "num_threads": process.num_threads(),
            }

        return self._safe_execute("file stats", _collect_file_stats, {})

    def _get_process_network_stats(self, process) -> Dict[str, Any]:
        """Get network connection statistics with safe execution."""

        def _collect_network_stats():
            connections = process.net_connections()
            return {
                "num_connections": len(connections),
                "connections_by_status": self._count_connections_by_status(connections),
            }

        return self._safe_execute("network stats", _collect_network_stats, {})

    def _get_process_context_stats(self, process) -> Dict[str, Any]:
        """Get context switch statistics with safe execution."""

        def _collect_context_stats():
            ctx_switches = process.num_ctx_switches()
            return {
                "ctx_switches_voluntary": ctx_switches.voluntary,
                "ctx_switches_involuntary": ctx_switches.involuntary,
            }

        return self._safe_execute("context stats", _collect_context_stats, {})

    def _get_process_path_stats(self, process) -> Dict[str, Any]:
        """Get working directory and command line information with safe execution."""

        def _collect_path_stats():
            cmdline = process.cmdline()
            return {
                "cwd": process.cwd(),
                "cmdline": " ".join(cmdline[:3]) + ("..." if len(cmdline) > 3 else ""),
            }

        return self._safe_execute("path stats", _collect_path_stats, {})

    @staticmethod
    def _count_connections_by_status(connections) -> Dict[str, int]:
        """Count network connections by their status."""
        status_counts = {}
        for conn in connections:
            status = conn.status if hasattr(conn, "status") else "UNKNOWN"
            status_counts[status] = status_counts.get(status, 0) + 1
        return status_counts

    def get_current_process_health_summary(self) -> Dict[str, Any]:
        """
        Get a compact health summary for the current process suitable for logging.

        Returns:
            Dictionary with key health metrics for logging.
        """

        def _get_health_summary():
            try:
                process = self._psutil.Process()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return {}

            summary = {}

            # Essential metrics with error handling
            with suppress(Exception):
                cpu_percent = process.cpu_percent(interval=0.1)
                summary["cpu"] = f"{cpu_percent:.1f}%"

            with suppress(Exception):
                memory_info = process.memory_info()
                memory_percent = process.memory_percent()
                summary.update(
                    {
                        "memory_rss": set_naturalsize(memory_info.rss),
                        "memory_percent": f"{memory_percent:.1f}%",
                    }
                )

            with suppress(Exception):
                summary.update(
                    {
                        "threads": process.num_threads(),
                        "status": process.status(),
                    }
                )

            # IO activity indicator
            with suppress(Exception):
                io_counters = process.io_counters()
                summary.update(
                    {
                        "io_reads": io_counters.read_count,
                        "io_writes": io_counters.write_count,
                    }
                )

            return summary

        return self._safe_execute(
            "health summary", _get_health_summary, {}, operation_type="health_check"
        )

    def get_load_average(self) -> LoadAverage:
        """Get system load averages."""
        return self._safe_execute(
            "load averages", self._psutil.getloadavg, (0.0, 0.0, 0.0)
        )

    def get_memory(self) -> MemoryStats:
        """Get memory statistics with natural size formatting."""
        memory_attrs = [
            "total",
            "available",
            "percent",
            "used",
            "free",
            "active",
            "inactive",
            "cached",
            "shared",
        ]

        def _get_memory():
            stats = self._psutil.virtual_memory()
            return {
                attr: (
                    set_naturalsize(getattr(stats, attr))
                    if attr != "percent"
                    else getattr(stats, attr)
                )
                for attr in memory_attrs
                if hasattr(stats, attr)
            }

        return self._safe_execute("memory stats", _get_memory, {})

    def get_disk_usage(self) -> list[DiskStats]:
        """Get disk usage statistics for all mounted partitions."""

        def _get_disk_stats():
            stats = []
            for fs in self._psutil.disk_partitions(all=False):
                with suppress(Exception):
                    usage = self._psutil.disk_usage(fs.mountpoint)
                    stats.append(
                        {
                            "device_name": fs.device,
                            "fs_type": fs.fstype,
                            "mnt_point": fs.mountpoint.replace("\u00a0", " "),
                            "size": set_naturalsize(usage.total),
                            "used": set_naturalsize(usage.used),
                            "free": set_naturalsize(usage.free),
                            "percent": usage.percent,
                        }
                    )
            return stats

        return self._safe_execute("disk usage", _get_disk_stats, [])

    def get_swap_memory(self) -> SwapStats:
        """Get swap memory usage statistics."""

        def _get_swap():
            swap = self._psutil.swap_memory()
            return {
                "total": set_naturalsize(swap.total),
                "used": set_naturalsize(swap.used),
                "free": set_naturalsize(swap.free),
                "percent": swap.percent,
            }

        return self._safe_execute("swap memory", _get_swap, {})

    def get_sensors_temperatures(self) -> list[SensorStats]:
        """Get sensor temperatures."""

        def _get_temps():
            sensors = []
            temps = self._psutil.sensors_temperatures()
            if not temps:
                return sensors

            for name, stats in temps.items():
                if stats and len(stats) > 0:
                    sensors.append({"sensor_name": name, "sensor_value": stats[0][1]})
            return sensors

        return self._safe_execute("sensor temperatures", _get_temps, [])

    @staticmethod
    def get_uptime() -> str:
        """Get system uptime as a formatted string."""
        try:
            uptime = datetime.now() - datetime.fromtimestamp(psutil.boot_time())
            return str(uptime).split(".")[0]
        except Exception as e:
            logger.error("Failed to get uptime", extra={"error": str(e)})
            return "unknown"

    def get_process_counts(self) -> ProcessStats:
        """Get process counts by status."""

        def _get_counts():
            counts = {
                status: sum(
                    1
                    for proc in self._psutil.process_iter(["status"])
                    if proc.info["status"] == status
                )
                for status in ("running", "sleeping", "idle")
            }
            counts["total"] = sum(counts.values())
            return counts

        return self._safe_execute("process counts", _get_counts, {})

    def get_net_io_counters(self) -> list[NetworkIOStats]:
        """Get network I/O statistics."""

        def _get_net_io():
            stats = self._psutil.net_io_counters()
            return [
                {
                    "bytes_sent": set_naturalsize(stats.bytes_sent),
                    "bytes_recv": set_naturalsize(stats.bytes_recv),
                    "packets_sent": stats.packets_sent,
                    "packets_recv": stats.packets_recv,
                    "err_in": stats.errin,
                    "err_out": stats.errout,
                    "drop_in": stats.dropin,
                    "drop_out": stats.dropout,
                }
            ]

        return self._safe_execute("network I/O", _get_net_io, [])

    def get_users_info(self) -> list[UserInfo]:
        """Get information about logged-in users."""

        def _get_users():
            return [
                {
                    "username": user.name,
                    "terminal": user.terminal,
                    "host": user.host,
                    "started": user.started,
                }
                for user in self._psutil.users()
            ]

        return self._safe_execute("users info", _get_users, [])

    def get_net_interface_stats(self) -> dict[str, NetworkInterfaceStats]:
        """Get network interface statistics."""

        def _get_net_stats():
            if_stats = self._psutil.net_if_stats()
            if_addrs = self._psutil.net_if_addrs()

            return {
                interface: {
                    "is_up": stats.isup,
                    "speed": stats.speed,
                    "duplex": stats.duplex,
                    "mtu": stats.mtu,
                    "ip_address": (
                        if_addrs[interface][0].address
                        if interface in if_addrs and if_addrs[interface]
                        else "N/A"
                    ),
                }
                for interface, stats in if_stats.items()
            }

        return self._safe_execute("network interface stats", _get_net_stats, {})

    def get_cpu_frequency(self) -> CPUFrequencyStats:
        """Get CPU frequency information."""

        def _get_cpu_freq():
            freq = self._psutil.cpu_freq()
            return {
                "current_freq": freq.current,
                "min_freq": freq.min,
                "max_freq": freq.max,
            }

        return self._safe_execute("CPU frequency", _get_cpu_freq, {})

    def get_cpu_usage(self) -> CPUUsageStats:
        """Get CPU usage statistics."""

        def _get_cpu_usage():
            return {
                "cpu_percent": self._psutil.cpu_percent(interval=1),
                "cpu_percent_per_core": self._psutil.cpu_percent(
                    interval=1, percpu=True
                ),
            }

        return self._safe_execute(
            "CPU usage",
            _get_cpu_usage,
            {"cpu_percent": 0.0, "cpu_percent_per_core": []},
        )

    def get_top_processes(self, count: int = 10) -> list[TopProcess]:
        """Get the top processes by CPU and memory usage."""

        if count <= 0 or count > 20:
            raise ValueError("Count must be between 1 and 20")

        def _get_top_processes():
            processes = []
            for proc in self._psutil.process_iter(
                ["pid", "name", "cpu_percent", "memory_percent"]
            ):
                with suppress(Exception):  # Suppress errors for inaccessible processes
                    cpu_percent = proc.info["cpu_percent"] or 0.0
                    memory_percent = proc.info["memory_percent"] or 0.0
                    processes.append(
                        {
                            "pid": proc.info["pid"],
                            "name": proc.info["name"],
                            "cpu_percent": cpu_percent,
                            "memory_percent": memory_percent,
                        }
                    )

            # Sort by CPU and memory usage, then take the top `count` processes
            sorted_processes = sorted(
                processes,
                key=lambda p: (p["cpu_percent"], p["memory_percent"]),
                reverse=True,
            )
            return sorted_processes[:count]

        return self._safe_execute("top processes", _get_top_processes, [])

    def get_cpu_count(self) -> int:
        """Get the number of CPU cores."""
        return self._psutil.cpu_count()
