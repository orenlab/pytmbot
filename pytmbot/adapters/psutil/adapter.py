#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import concurrent.futures
import os
import time
from collections.abc import Callable, Sequence
from contextlib import suppress
from datetime import datetime
from functools import lru_cache, wraps
from threading import RLock
from typing import Any, TypeVar
from uuid import uuid4

import psutil

from pytmbot.adapters.psutil.adapter_types import (
    CPUFrequencyStats,
    CPUUsageStats,
    DiskStats,
    LoadAverage,
    MemoryStats,
    NetworkInterfaceStats,
    NetworkIOStats,
    ProcessStats,
    SensorStats,
    SwapStats,
    TopProcess,
    UserInfo,
)
from pytmbot.logs import Logger
from pytmbot.utils import set_naturalsize

logger = Logger()
R = TypeVar("R")


def thread_safe_cache(
    maxsize: int = 128, ttl_seconds: float = 5.0
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Thread-safe cache decorator with TTL for expensive operations."""

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        cache: dict[
            tuple[tuple[Any, ...], tuple[tuple[str, Any], ...]],
            tuple[Any, float],
        ] = {}
        cache_lock = RLock()

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            # Create cache key including both args and kwargs
            cache_key = (args, tuple(sorted(kwargs.items())))
            current_time = time.time()

            with cache_lock:
                if cache_key in cache:
                    result, timestamp = cache[cache_key]
                    if current_time - timestamp < ttl_seconds:
                        return result

                # Clean expired entries
                expired_keys = [
                    key
                    for key, (_, timestamp) in cache.items()
                    if current_time - timestamp >= ttl_seconds
                ]
                for key in expired_keys:
                    cache.pop(key, None)

                # Limit cache size
                if len(cache) >= maxsize:
                    # Remove oldest entries
                    oldest_key = min(cache.keys(), key=lambda k: cache[k][1])
                    cache.pop(oldest_key, None)

                # Execute function and cache result
                result = func(*args, **kwargs)
                cache[cache_key] = (result, current_time)
                return result

        return wrapper

    return decorator


class PsutilAdapter:
    """Provides system statistics using psutil with advanced error handling and thread safety."""

    # Class-level constants for better maintainability
    _DEFAULT_TIMEOUT = 2.0
    _MAX_CONCURRENT_WORKERS = 4
    _MAX_TOP_PROCESSES = 20
    _MEMORY_ATTRS = frozenset(
        [
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
    )

    def __init__(self) -> None:
        self._psutil = psutil
        self._lock = RLock()  # Thread safety for instance-level operations

    @staticmethod
    def _safe_execute(
        operation: str,
        func: Callable[[], R],
        fallback: R,
        *,
        timeout: float | None = None,
        **log_context: Any,
    ) -> tuple[R, float]:
        """
        Execute operation safely with optional timeout.

        Args:
            operation: Description of the operation for logging
            func: Function to execute
            fallback: Value to return on failure
            timeout: Optional timeout in seconds
            **log_context: Additional context for logging
        """
        start_time = time.perf_counter()
        span_context = {**log_context, "span_id": uuid4().hex[:8]}

        try:
            if timeout:
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(func)
                    result = future.result(timeout=timeout)
            else:
                result = func()

            execution_time_ms = (time.perf_counter() - start_time) * 1000
            return result, execution_time_ms

        except concurrent.futures.TimeoutError:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(
                f"Operation timed out: {operation}",
                timeout_seconds=timeout,
                ms=round(execution_time_ms, 2),
                **span_context,
            )
            return fallback, execution_time_ms

        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(
                f"Process access issue: {operation}",
                error=str(e),
                error_type=type(e).__name__,
                ms=round(execution_time_ms, 2),
                **span_context,
            )
            return fallback, execution_time_ms

        except Exception as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                f"Operation failed: {operation}",
                error=str(e),
                error_type=type(e).__name__,
                ms=round(execution_time_ms, 2),
                **span_context,
            )
            return fallback, execution_time_ms

    @staticmethod
    def _log_operation_result(
        message: str,
        execution_time_ms: float,
        **context: Any,
    ) -> None:
        """Log a single operation result line with semantic level by latency."""
        payload = {**context, "ms": round(execution_time_ms, 2)}

        level = "debug" if execution_time_ms < 100 else "info"
        getattr(logger, level)(message, **payload)

    @staticmethod
    def _log_trace_operation_result(
        message: str,
        execution_time_ms: float,
        **context: Any,
    ) -> None:
        """Log low-priority periodic operation results on TRACE."""
        payload = {**context, "ms": round(execution_time_ms, 2)}
        logger.trace(message, **payload)

    def get_process_stats(self, pid: int | None = None) -> dict[str, Any]:
        """
        Get comprehensive statistics for a specific process.

        Args:
            pid: Process ID. If None, uses current process.

        Returns:
            Dictionary with process statistics including CPU, memory, IO, etc.

        Raises:
            ValueError: If pid is provided but is not a positive integer.
        """
        if pid is not None and (not isinstance(pid, int) or pid <= 0):
            raise ValueError("PID must be a positive integer")

        target_pid = pid or os.getpid()
        context = {"action": "process_stats", "pid": target_pid}

        def _get_process_info():
            try:
                process = self._psutil.Process(target_pid)

                # Validate process exists and is accessible
                _ = process.pid  # This will raise if process doesn't exist

            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                logger.warning(
                    "Process access denied or not found", error=str(e), **context
                )
                return {}

            # Define collectors with better error isolation
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

            stats = self._collect_stats_concurrently(stats_collectors)
            return stats

        result, execution_time_ms = self._safe_execute(
            "process stats collection",
            _get_process_info,
            {},
            timeout=self._DEFAULT_TIMEOUT * 2,  # More time for comprehensive stats
            **context,
        )
        self._log_operation_result(
            "Process statistics",
            execution_time_ms,
            categories=len(result),
            **context,
        )
        return result

    def _collect_stats_concurrently(
        self, collectors: Sequence[tuple[str, Callable[[], dict[str, Any]]]]
    ) -> dict[str, Any]:
        """
        Collect statistics concurrently using ThreadPoolExecutor with improved error handling.

        Args:
            collectors: Sequence of (name, collector_function) tuples

        Returns:
            Merged dictionary of all collected statistics
        """
        final_stats = {}
        context = {"action": "concurrent_stats_collection"}
        successful_collections = 0

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(self._MAX_CONCURRENT_WORKERS, len(collectors)),
            thread_name_prefix="psutil_stats",
        ) as executor:
            # Submit all tasks with better future management
            future_to_name = {
                executor.submit(collector): name for name, collector in collectors
            }

            # Collect results as they complete with timeout per operation
            for future in concurrent.futures.as_completed(
                future_to_name, timeout=self._DEFAULT_TIMEOUT * len(collectors)
            ):
                name = future_to_name[future]
                try:
                    stats = future.result(timeout=self._DEFAULT_TIMEOUT)
                    if stats:  # Only update if we got valid stats
                        final_stats.update(stats)
                        successful_collections += 1
                        logger.trace(f"Collected {name} stats", **context)

                except concurrent.futures.TimeoutError:
                    logger.warning(
                        f"Timeout collecting {name} stats",
                        timeout_seconds=self._DEFAULT_TIMEOUT,
                        collector=name,
                        **context,
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to collect {name} stats",
                        error=str(e),
                        error_type=type(e).__name__,
                        collector=name,
                        **context,
                    )

        logger.trace(
            "Concurrent stats collection completed",
            collected_categories=successful_collections,
            total_categories=len(collectors),
            **context,
        )
        return final_stats

    def _get_basic_process_info(self, process: psutil.Process) -> dict[str, Any]:
        """Get basic process information with safe execution."""

        def _collect():
            return {
                "pid": process.pid,
                "name": process.name(),
                "status": process.status(),
                "create_time": process.create_time(),
                "parent_pid": getattr(process.parent(), "pid", None)
                if process.parent()
                else None,
            }

        result, _ = self._safe_execute("basic process info", _collect, {})
        return result

    def _get_process_cpu_stats(self, process: psutil.Process) -> dict[str, Any]:
        """Get CPU-related process statistics with safe execution."""

        def _collect_cpu_stats():
            # Use shorter interval for responsiveness in sync bot
            cpu_percent = process.cpu_percent(interval=0.05)  # Reduced from 0.1
            cpu_times = process.cpu_times()

            stats = {
                "cpu_percent": f"{cpu_percent:.1f}%",
                "cpu_times": cpu_times._asdict(),
            }

            # Add CPU affinity if available and accessible
            with suppress(AttributeError, psutil.AccessDenied):
                affinity = process.cpu_affinity()
                if affinity is not None:
                    stats["cpu_affinity"] = len(affinity)

            # Add CPU number if available (Linux)
            with suppress(AttributeError, psutil.AccessDenied):
                cpu_num = process.cpu_num()
                if cpu_num is not None:
                    stats["cpu_num"] = cpu_num

            return stats

        result, _ = self._safe_execute("CPU stats", _collect_cpu_stats, {})
        return result

    def _get_process_memory_stats(self, process: psutil.Process) -> dict[str, Any]:
        """Get memory-related process statistics with safe execution."""

        def _collect_memory_stats():
            memory_info = process.memory_info()
            memory_percent = process.memory_percent()

            stats = {
                "memory_rss": set_naturalsize(memory_info.rss),
                "memory_vms": set_naturalsize(memory_info.vms),
                "memory_percent": f"{memory_percent:.1f}%",
            }

            # Extended memory info with better error handling
            with suppress(AttributeError, psutil.AccessDenied, OSError):
                full_memory = process.memory_full_info()
                stats.update(
                    {
                        "memory_uss": set_naturalsize(full_memory.uss),
                        "memory_pss": set_naturalsize(full_memory.pss),
                    }
                )

            # Memory maps count
            with suppress(AttributeError, psutil.AccessDenied):
                memory_maps = process.memory_maps()
                if memory_maps is not None:
                    stats["memory_maps_count"] = len(memory_maps)

            return stats

        result, _ = self._safe_execute("memory stats", _collect_memory_stats, {})
        return result

    def _get_process_io_stats(self, process: psutil.Process) -> dict[str, Any]:
        """Get I/O statistics for the process with safe execution."""

        def _collect_io_stats():
            io_counters = process.io_counters()
            return {
                "io_read_count": io_counters.read_count,
                "io_write_count": io_counters.write_count,
                "io_read_bytes": set_naturalsize(io_counters.read_bytes),
                "io_write_bytes": set_naturalsize(io_counters.write_bytes),
                "io_read_chars": getattr(io_counters, "read_chars", 0),
                "io_write_chars": getattr(io_counters, "write_chars", 0),
            }

        result, _ = self._safe_execute("I/O stats", _collect_io_stats, {})
        return result

    def _get_process_file_stats(self, process: psutil.Process) -> dict[str, Any]:
        """Get file descriptor and thread statistics with safe execution."""

        def _collect_file_stats():
            stats = {"num_threads": process.num_threads()}

            # File descriptors (Unix-like systems)
            if hasattr(process, "num_fds"):
                with suppress(psutil.AccessDenied):
                    stats["num_fds"] = process.num_fds()
            else:
                stats["num_fds"] = "N/A"

            # Handle count (Windows)
            if hasattr(process, "num_handles"):
                with suppress(psutil.AccessDenied):
                    stats["num_handles"] = process.num_handles()

            return stats

        result, _ = self._safe_execute("file stats", _collect_file_stats, {})
        return result

    def _get_process_network_stats(self, process: psutil.Process) -> dict[str, Any]:
        """Get network connection statistics with safe execution."""

        def _collect_network_stats():
            with suppress(psutil.AccessDenied):
                connections = process.net_connections()
                return {
                    "num_connections": len(connections),
                    "connections_by_status": self._count_connections_by_status(
                        connections
                    ),
                }
            return {"num_connections": 0, "connections_by_status": {}}

        result, _ = self._safe_execute("network stats", _collect_network_stats, {})
        return result

    def _get_process_context_stats(self, process: psutil.Process) -> dict[str, Any]:
        """Get context switch statistics with safe execution."""

        def _collect_context_stats():
            ctx_switches = process.num_ctx_switches()
            return {
                "ctx_switches_voluntary": ctx_switches.voluntary,
                "ctx_switches_involuntary": ctx_switches.involuntary,
                "ctx_switches_total": ctx_switches.voluntary + ctx_switches.involuntary,
            }

        result, _ = self._safe_execute("context stats", _collect_context_stats, {})
        return result

    def _get_process_path_stats(self, process: psutil.Process) -> dict[str, Any]:
        """Get working directory and command line information with safe execution."""

        def _collect_path_stats():
            stats = {}

            # Working directory
            with suppress(psutil.AccessDenied, OSError):
                stats["cwd"] = process.cwd()

            # Command line with safe truncation
            with suppress(psutil.AccessDenied):
                cmdline = process.cmdline()
                if cmdline:
                    # More intelligent truncation
                    cmd_str = " ".join(cmdline)
                    if len(cmd_str) > 100:
                        stats["cmdline"] = cmd_str[:97] + "..."
                    else:
                        stats["cmdline"] = cmd_str
                else:
                    stats["cmdline"] = "<no command line>"

            # Executable path
            with suppress(psutil.AccessDenied, OSError):
                stats["exe"] = process.exe()

            return stats

        result, _ = self._safe_execute("path stats", _collect_path_stats, {})
        return result

    @staticmethod
    def _count_connections_by_status(connections: Sequence[Any]) -> dict[str, int]:
        """Count network connections by their status with improved typing."""
        status_counts: dict[str, int] = {}
        for conn in connections:
            status = getattr(conn, "status", "UNKNOWN")
            status_counts[status] = status_counts.get(status, 0) + 1
        return status_counts

    @thread_safe_cache(maxsize=1, ttl_seconds=2.0)  # Cache for 2 seconds
    def get_current_process_health_summary(self) -> dict[str, Any]:
        """
        Get a compact health summary for the current process suitable for logging.
        Cached for 2 seconds to avoid excessive system calls.

        Returns:
            Dictionary with key health metrics for logging.
        """
        context = {"action": "health_summary"}

        def _get_health_summary():
            try:
                process = self._psutil.Process()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return {}

            summary = {}

            # Essential metrics with error handling
            with suppress(Exception):
                cpu_percent = process.cpu_percent(interval=0.05)  # Reduced interval
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

            # Add uptime
            with suppress(Exception):
                create_time = process.create_time()
                uptime = time.time() - create_time
                summary["uptime_seconds"] = round(uptime, 1)

            return summary

        result, execution_time_ms = self._safe_execute(
            "health summary",
            _get_health_summary,
            {},
            timeout=1.0,  # Quick timeout for health checks
            **context,
        )
        self._log_trace_operation_result(
            "Process health",
            execution_time_ms,
            cpu=result.get("cpu"),
            memory=result.get("memory_percent"),
            threads=result.get("threads"),
            **context,
        )
        return result

    @thread_safe_cache(maxsize=1, ttl_seconds=5.0)
    def get_load_average(self) -> LoadAverage:
        """Get system load averages. Cached for 5 seconds."""
        context = {"action": "load_average"}

        def _get_load():
            try:
                return self._psutil.getloadavg()
            except (AttributeError, OSError):
                # getloadavg not available on Windows
                return (0.0, 0.0, 0.0)

        result, execution_time_ms = self._safe_execute(
            "load averages", _get_load, (0.0, 0.0, 0.0), **context
        )
        self._log_operation_result(
            "Load averages",
            execution_time_ms,
            load_1m=result[0],
            load_5m=result[1],
            load_15m=result[2],
            **context,
        )
        return result

    @thread_safe_cache(maxsize=1, ttl_seconds=3.0)
    def get_memory(self) -> MemoryStats:
        """Get memory statistics with natural size formatting. Cached for 3 seconds."""
        context = {"action": "memory_stats"}

        def _get_memory():
            stats = self._psutil.virtual_memory()
            result = {}

            for attr in self._MEMORY_ATTRS:
                if hasattr(stats, attr):
                    value = getattr(stats, attr)
                    if attr == "percent":
                        result[attr] = value
                    else:
                        result[attr] = set_naturalsize(value)
            return result

        result, execution_time_ms = self._safe_execute(
            "memory stats", _get_memory, {}, **context
        )
        self._log_operation_result(
            "Memory stats",
            execution_time_ms,
            total=result.get("total"),
            available=result.get("available"),
            percent=result.get("percent"),
            **context,
        )
        return result

    @thread_safe_cache(maxsize=1, ttl_seconds=10.0)
    def get_disk_usage(self) -> list[DiskStats]:
        """Get disk usage statistics for all mounted partitions. Cached for 10 seconds."""
        context = {"action": "disk_usage"}

        def _get_disk_stats():
            stats = []
            partitions = self._psutil.disk_partitions(all=False)

            for fs in partitions:
                with suppress(Exception):
                    usage = self._psutil.disk_usage(fs.mountpoint)
                    stats.append(
                        {
                            "device_name": fs.device,
                            "fs_type": fs.fstype,
                            "mnt_point": fs.mountpoint.replace(
                                "\u00a0", " "
                            ),  # Non-breaking space fix
                            "size": set_naturalsize(usage.total),
                            "used": set_naturalsize(usage.used),
                            "free": set_naturalsize(usage.free),
                            "percent": round(usage.percent, 1),  # Round for consistency
                        }
                    )

            return stats

        result, execution_time_ms = self._safe_execute(
            "disk usage", _get_disk_stats, [], **context
        )
        self._log_operation_result(
            "Disk usage",
            execution_time_ms,
            partitions_count=len(result),
            **context,
        )
        return result

    @thread_safe_cache(maxsize=1, ttl_seconds=5.0)
    def get_swap_memory(self) -> SwapStats:
        """Get swap memory usage statistics. Cached for 5 seconds."""
        context = {"action": "swap_memory"}

        def _get_swap():
            swap = self._psutil.swap_memory()
            result = {
                "total": set_naturalsize(swap.total),
                "used": set_naturalsize(swap.used),
                "free": set_naturalsize(swap.free),
                "percent": round(swap.percent, 1),
            }
            return result

        result, execution_time_ms = self._safe_execute(
            "swap memory", _get_swap, {}, **context
        )
        self._log_operation_result(
            "Swap memory",
            execution_time_ms,
            total=result.get("total"),
            used=result.get("used"),
            percent=result.get("percent"),
            **context,
        )
        return result

    @thread_safe_cache(maxsize=1, ttl_seconds=15.0)
    def get_sensors_temperatures(self) -> list[SensorStats]:
        """Get sensor temperatures. Cached for 15 seconds."""
        context = {"action": "sensors_temperatures"}

        def _get_temps():
            sensors = []
            try:
                temps = self._psutil.sensors_temperatures()
                if not temps:
                    return sensors

                for name, stats_list in temps.items():
                    if stats_list and len(stats_list) > 0:
                        # Take the first sensor of each type, validate temperature
                        temp_value = stats_list[0].current
                        if (
                            temp_value is not None and -50 <= temp_value <= 150
                        ):  # Reasonable range
                            sensors.append(
                                {
                                    "sensor_name": name,
                                    "sensor_value": round(temp_value, 1),
                                }
                            )

            except (AttributeError, OSError):
                # sensors_temperatures not available on this system
                pass

            return sensors

        result, execution_time_ms = self._safe_execute(
            "sensor temperatures", _get_temps, [], **context
        )
        self._log_operation_result(
            "Sensor temperatures",
            execution_time_ms,
            sensors_count=len(result),
            **context,
        )
        return result

    @lru_cache(maxsize=1)
    def get_uptime(self) -> str:
        """Get system uptime as a formatted string. Cached until process restart."""
        context = {"action": "uptime"}

        def _get_uptime() -> str:
            boot_time = psutil.boot_time()
            uptime = datetime.now() - datetime.fromtimestamp(boot_time)
            return str(uptime).split(".")[0]  # Remove microseconds

        result, execution_time_ms = self._safe_execute(
            "uptime", _get_uptime, "unknown", **context
        )
        self._log_operation_result(
            "System uptime",
            execution_time_ms,
            uptime=result,
            **context,
        )
        return result

    @thread_safe_cache(maxsize=1, ttl_seconds=5.0)
    def get_process_counts(self) -> ProcessStats:
        """Get process counts by status. Cached for 5 seconds."""
        context = {"action": "process_counts"}

        def _get_counts():
            status_counts = {"running": 0, "sleeping": 0, "idle": 0, "other": 0}

            try:
                for proc in self._psutil.process_iter(["status"]):
                    with suppress(Exception):
                        status = proc.info.get("status", "unknown")
                        if status in status_counts:
                            status_counts[status] += 1
                        else:
                            status_counts["other"] += 1

            except Exception as e:
                logger.warning("Error iterating processes", error=str(e), **context)
                return {"running": 0, "sleeping": 0, "idle": 0, "total": 0}

            # Calculate total
            total = sum(status_counts.values())
            result = {
                "running": status_counts["running"],
                "sleeping": status_counts["sleeping"],
                "idle": status_counts["idle"],
                "total": total,
            }
            return result

        result, execution_time_ms = self._safe_execute(
            "process counts", _get_counts, {}, **context
        )
        self._log_operation_result(
            "Process counts",
            execution_time_ms,
            total=result.get("total"),
            running=result.get("running"),
            sleeping=result.get("sleeping"),
            **context,
        )
        return result

    @thread_safe_cache(maxsize=1, ttl_seconds=5.0)
    def get_net_io_counters(self) -> list[NetworkIOStats]:
        """Get network I/O statistics. Cached for 5 seconds."""
        context = {"action": "network_io"}

        def _get_net_io():
            stats = self._psutil.net_io_counters()
            if not stats:
                return []

            result = [
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
            return result

        result, execution_time_ms = self._safe_execute(
            "network I/O", _get_net_io, [], **context
        )
        first_entry = result[0] if result else {}
        self._log_operation_result(
            "Network I/O",
            execution_time_ms,
            bytes_sent=first_entry.get("bytes_sent"),
            bytes_recv=first_entry.get("bytes_recv"),
            **context,
        )
        return result

    @thread_safe_cache(maxsize=1, ttl_seconds=10.0)
    def get_users_info(self) -> list[UserInfo]:
        """Get information about logged-in users. Cached for 10 seconds."""
        context = {"action": "users_info"}

        def _get_users():
            users = []
            try:
                for user in self._psutil.users():
                    users.append(
                        {
                            "username": user.name,
                            "terminal": getattr(user, "terminal", "unknown"),
                            "host": getattr(user, "host", "localhost"),
                            "started": user.started,
                        }
                    )
            except Exception as e:
                logger.warning("Error retrieving users", error=str(e), **context)
            return users

        result, execution_time_ms = self._safe_execute(
            "users info", _get_users, [], **context
        )
        self._log_operation_result(
            "Users info",
            execution_time_ms,
            users_count=len(result),
            **context,
        )
        return result

    @thread_safe_cache(maxsize=1, ttl_seconds=10.0)
    def get_net_interface_stats(self) -> dict[str, NetworkInterfaceStats]:
        """Get network interface statistics. Cached for 10 seconds."""
        context = {"action": "network_interfaces"}

        def _get_net_stats():
            try:
                if_stats = self._psutil.net_if_stats()
                if_addrs = self._psutil.net_if_addrs()
            except Exception as e:
                logger.warning(
                    "Error retrieving network interfaces", error=str(e), **context
                )
                return {}

            result = {}
            for interface, stats in if_stats.items():
                with suppress(Exception):
                    # Get first IPv4 address or fallback
                    ip_address = "N/A"
                    if interface in if_addrs and if_addrs[interface]:
                        for addr in if_addrs[interface]:
                            if addr.family.name == "AF_INET":  # IPv4
                                ip_address = addr.address
                                break

                    result[interface] = {
                        "is_up": stats.isup,
                        "speed": stats.speed if stats.speed > 0 else 0,
                        "duplex": getattr(stats, "duplex", "unknown"),
                        "mtu": stats.mtu,
                        "ip_address": ip_address,
                    }

            return result

        result, execution_time_ms = self._safe_execute(
            "network interface stats", _get_net_stats, {}, **context
        )
        active_interfaces = sum(1 for stats in result.values() if stats["is_up"])
        self._log_operation_result(
            "Network interfaces",
            execution_time_ms,
            total_interfaces=len(result),
            active_interfaces=active_interfaces,
            **context,
        )
        return result

    @thread_safe_cache(maxsize=1, ttl_seconds=5.0)
    def get_cpu_frequency(self) -> CPUFrequencyStats:
        """Get CPU frequency information. Cached for 5 seconds."""
        context = {"action": "cpu_frequency"}

        def _get_cpu_freq():
            try:
                freq = self._psutil.cpu_freq()
                if freq is None:
                    return {"current_freq": 0.0, "min_freq": 0.0, "max_freq": 0.0}

                result = {
                    "current_freq": round(freq.current, 1) if freq.current else 0.0,
                    "min_freq": round(freq.min, 1) if freq.min else 0.0,
                    "max_freq": round(freq.max, 1) if freq.max else 0.0,
                }
                return result

            except (AttributeError, OSError):
                # CPU frequency not available on this system
                return {"current_freq": 0.0, "min_freq": 0.0, "max_freq": 0.0}

        result, execution_time_ms = self._safe_execute(
            "CPU frequency", _get_cpu_freq, {}, **context
        )
        self._log_operation_result(
            "CPU frequency",
            execution_time_ms,
            current=result.get("current_freq"),
            min=result.get("min_freq"),
            max=result.get("max_freq"),
            **context,
        )
        return result

    def get_cpu_usage(self) -> CPUUsageStats:
        """
        Get CPU usage statistics.

        Note: Not cached due to the nature of CPU usage measurement requiring intervals.
        """
        context = {"action": "cpu_usage"}

        def _get_cpu_usage():
            # Use shorter interval for sync bot responsiveness
            interval = 0.5  # Reduced from 1.0 second

            cpu_percent = self._psutil.cpu_percent(interval=interval)
            cpu_per_core = self._psutil.cpu_percent(interval=0.1, percpu=True)

            result = {
                "cpu_percent": round(cpu_percent, 1),
                "cpu_percent_per_core": [round(core, 1) for core in cpu_per_core],
            }
            return result

        result, execution_time_ms = self._safe_execute(
            "CPU usage",
            _get_cpu_usage,
            {"cpu_percent": 0.0, "cpu_percent_per_core": []},
            timeout=2.0,  # Allow more time for CPU measurement
            **context,
        )
        self._log_operation_result(
            "CPU usage",
            execution_time_ms,
            overall_cpu=f"{result.get('cpu_percent', 0.0):.1f}%",
            cores_count=len(result.get("cpu_percent_per_core", [])),
            **context,
        )
        return result

    def get_top_processes(self, count: int = 10) -> list[TopProcess]:
        """
        Get the top processes by CPU and memory usage.

        Args:
            count: Number of processes to return (1-20)

        Raises:
            ValueError: If count is not between 1 and 20
        """
        if not isinstance(count, int) or count <= 0 or count > self._MAX_TOP_PROCESSES:
            raise ValueError(f"Count must be between 1 and {self._MAX_TOP_PROCESSES}")

        context = {"action": "top_processes", "count": count}

        def _get_top_processes():
            processes = []
            excluded_processes = 0

            try:
                # Get processes with required info
                for proc in self._psutil.process_iter(
                    ["pid", "name", "cpu_percent", "memory_percent", "status"]
                ):
                    with suppress(
                        Exception
                    ):  # Suppress errors for inaccessible processes
                        info = proc.info

                        # Skip processes we can't measure
                        if info["status"] in ("zombie", "stopped"):
                            excluded_processes += 1
                            continue

                        cpu_percent = info.get("cpu_percent") or 0.0
                        memory_percent = info.get("memory_percent") or 0.0

                        # Only include processes with some activity
                        if cpu_percent > 0.1 or memory_percent > 0.1:
                            processes.append(
                                {
                                    "pid": info["pid"],
                                    "name": info["name"] or "unknown",
                                    "cpu_percent": round(cpu_percent, 1),
                                    "memory_percent": round(memory_percent, 1),
                                }
                            )

            except Exception as e:
                logger.warning(
                    "Error iterating processes for top list", error=str(e), **context
                )
                return []

            # Sort by combined CPU and memory usage (weighted average)
            sorted_processes = sorted(
                processes,
                key=lambda p: (p["cpu_percent"] * 0.6 + p["memory_percent"] * 0.4),
                reverse=True,
            )

            return sorted_processes[:count], len(processes), excluded_processes

        result, execution_time_ms = self._safe_execute(
            "top processes",
            _get_top_processes,
            ([], 0, 0),
            timeout=3.0,  # Allow more time for process iteration
            **context,
        )
        top_processes, processes_analyzed, excluded_processes = result
        top_cpu = f"{top_processes[0]['cpu_percent']:.1f}%" if top_processes else "0.0%"
        top_memory = (
            f"{top_processes[0]['memory_percent']:.1f}%" if top_processes else "0.0%"
        )
        self._log_operation_result(
            "Top processes",
            execution_time_ms,
            processes_analyzed=processes_analyzed,
            excluded_processes=excluded_processes,
            top_count=len(top_processes),
            top_cpu=top_cpu,
            top_memory=top_memory,
            **context,
        )
        return top_processes

    @lru_cache(maxsize=1)
    def get_cpu_count(self) -> int:
        """Get the number of CPU cores. Cached permanently."""
        context = {"action": "cpu_count"}
        result, execution_time_ms = self._safe_execute(
            "CPU count",
            lambda: self._psutil.cpu_count(logical=True) or 1,
            1,
            **context,
        )
        self._log_operation_result(
            "CPU count",
            execution_time_ms,
            cpu_cores=result,
            **context,
        )
        return result

    def clear_cache(self) -> None:
        """Clear all cached data. Useful for testing or forced refresh."""
        # Clear method-level caches
        for method_name in dir(self):
            method = getattr(self, method_name)
            if hasattr(method, "__wrapped__") and hasattr(method, "cache_clear"):
                try:
                    method.cache_clear()
                except AttributeError:
                    pass  # Not all cached methods support cache_clear

        logger.info("All caches cleared")

    def get_system_summary(self) -> dict[str, Any]:
        """
        Get a comprehensive system summary with all major metrics.

        Returns:
            Dictionary with system overview including CPU, memory, disk, and process info.
        """
        context = {"action": "system_summary"}

        def _collect_summary() -> dict[str, Any]:
            summary = {}
            collectors = [
                (
                    "cpu",
                    lambda: {"cpu_count": self.get_cpu_count(), **self.get_cpu_usage()},
                ),
                ("memory", lambda: self.get_memory()),
                ("load", lambda: {"load_average": self.get_load_average()}),
                ("processes", lambda: self.get_process_counts()),
                ("uptime", lambda: {"uptime": self.get_uptime()}),
            ]

            for name, collector in collectors:
                try:
                    data = collector()
                    if data:
                        summary[name] = data
                except Exception as e:
                    logger.warning(
                        f"Failed to collect {name} for system summary",
                        error=str(e),
                        **context,
                    )

            return summary

        result, execution_time_ms = self._safe_execute(
            "system summary",
            _collect_summary,
            {},
            **context,
        )
        self._log_operation_result(
            "System summary",
            execution_time_ms,
            categories=len(result),
            **context,
        )
        return result
