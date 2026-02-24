#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import concurrent.futures
import heapq
import os
import socket
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from datetime import datetime
from functools import lru_cache, wraps
from threading import RLock
from typing import Any, TypeVar
from uuid import uuid4

import psutil

from pytmbot.adapters.psutil.adapter_types import (
    CPUFrequencyStats,
    CPUTimesPercentStats,
    CPUUsageStats,
    DiskIOStats,
    DiskStats,
    FanSpeedStats,
    LoadAverage,
    MemoryStats,
    NetworkConnectionsSummary,
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
        cache: OrderedDict[
            tuple[tuple[Any, ...], tuple[tuple[str, Any], ...]],
            tuple[Any, float],
        ] = OrderedDict()
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
                        cache.move_to_end(cache_key)
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
                    cache.popitem(last=False)

                # Execute function and cache result
                result = func(*args, **kwargs)
                cache[cache_key] = (result, current_time)
                return result

        def cache_clear() -> None:
            with cache_lock:
                cache.clear()

        wrapper.cache_clear = cache_clear  # type: ignore[attr-defined]

        return wrapper

    return decorator


class PsutilAdapter:
    """Provides system statistics using psutil with advanced error handling and thread safety."""

    # Class-level constants for better maintainability
    _DEFAULT_TIMEOUT = 2.0
    _MAX_CONCURRENT_WORKERS = 4
    _MAX_TOP_PROCESSES = 20
    _CPU_WARMUP_INTERVAL_SECONDS = 1.0
    _CPU_USAGE_SAMPLE_PERIOD_SECONDS = 5.0
    _CPU_WARMUP_THREAD_JOIN_TIMEOUT_SECONDS = 1.5
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
        self._cpu_usage_lock = RLock()
        self._cpu_usage_snapshot: CPUUsageStats | None = None
        self._cpu_warmup_stop_event = threading.Event()
        self._cpu_warmup_thread: threading.Thread | None = None
        self._timeout_executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=2,
            thread_name_prefix="psutil_timeout",
        )
        self._start_cpu_warmup()

    def _start_cpu_warmup(self) -> None:
        """Start background CPU sampling to avoid blocking request handlers."""
        if self._cpu_warmup_thread and self._cpu_warmup_thread.is_alive():
            return

        self._cpu_warmup_stop_event.clear()
        self._cpu_warmup_thread = threading.Thread(
            target=self._cpu_warmup_worker,
            name="PsutilCpuWarmup",
            daemon=True,
        )
        self._cpu_warmup_thread.start()

    def _cpu_warmup_worker(self) -> None:
        """Collect CPU usage snapshots at a fixed cadence."""
        with suppress(Exception):
            self._psutil.cpu_percent(interval=0.0)
            self._psutil.cpu_percent(interval=0.0, percpu=True)

        while not self._cpu_warmup_stop_event.is_set():
            sample_start = time.monotonic()
            try:
                per_core_raw = self._psutil.cpu_percent(
                    interval=self._CPU_WARMUP_INTERVAL_SECONDS,
                    percpu=True,
                )
                per_core_values = [
                    round(float(value), 1)
                    for value in per_core_raw
                    if isinstance(value, (int, float))
                ]
                if per_core_values:
                    overall = round(sum(per_core_values) / len(per_core_values), 1)
                else:
                    overall_raw = self._psutil.cpu_percent(interval=0.0)
                    overall = (
                        round(float(overall_raw), 1)
                        if isinstance(overall_raw, (int, float))
                        else 0.0
                    )

                snapshot: CPUUsageStats = {
                    "cpu_percent": overall,
                    "cpu_percent_per_core": per_core_values,
                }
                with self._cpu_usage_lock:
                    self._cpu_usage_snapshot = snapshot
            except Exception as error:
                logger.debug(
                    "bot.system.cpu.warmup.fail",
                    error=str(error),
                    error_type=type(error).__name__,
                )

            elapsed_seconds = time.monotonic() - sample_start
            sleep_seconds = max(
                0.0, self._CPU_USAGE_SAMPLE_PERIOD_SECONDS - elapsed_seconds
            )
            if self._cpu_warmup_stop_event.wait(timeout=sleep_seconds):
                break

    def _safe_execute(
        self,
        operation: str,
        func: Callable[[], R],
        fallback: R,
        *,
        timeout: float | None = None,
        log_context: Mapping[str, object] | None = None,
    ) -> tuple[R, float]:
        """
        Execute operation safely with optional timeout.

        Args:
            operation: Description of the operation for logging
            func: Function to execute
            fallback: Value to return on failure
            timeout: Optional timeout in seconds
            log_context: Additional context for logging
        """
        del operation
        start_time = time.perf_counter()
        span_context: dict[str, object] = dict(log_context or {})
        span_context["span_id"] = uuid4().hex[:8]

        try:
            if timeout:
                future = self._timeout_executor.submit(func)
                result = future.result(timeout=timeout)
            else:
                result = func()

            execution_time_ms = (time.perf_counter() - start_time) * 1000
            return result, execution_time_ms

        except concurrent.futures.TimeoutError:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            if "future" in locals():
                future.cancel()
            logger.warning(
                "bot.system.timed.warn",
                timeout_seconds=timeout,
                ms=round(execution_time_ms, 2),
                **span_context,
            )
            return fallback, execution_time_ms

        except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.warning(
                "bot.system.access.issue.warn",
                error=str(e),
                error_type=type(e).__name__,
                ms=round(execution_time_ms, 2),
                **span_context,
            )
            return fallback, execution_time_ms

        except Exception as e:
            execution_time_ms = (time.perf_counter() - start_time) * 1000
            logger.error(
                "bot.system.fail",
                error=str(e),
                error_type=type(e).__name__,
                ms=round(execution_time_ms, 2),
                **span_context,
            )
            return fallback, execution_time_ms

    def close(self) -> None:
        """Release shared executor resources."""
        self._cpu_warmup_stop_event.set()
        warmup_thread = self._cpu_warmup_thread
        if (
            warmup_thread is not None
            and warmup_thread.is_alive()
            and warmup_thread is not threading.current_thread()
        ):
            warmup_thread.join(timeout=self._CPU_WARMUP_THREAD_JOIN_TIMEOUT_SECONDS)
        self._cpu_warmup_thread = None
        self._timeout_executor.shutdown(wait=False, cancel_futures=True)

    def __del__(self) -> None:
        """Best-effort cleanup on object destruction."""
        try:
            self.close()
        except (AttributeError, RuntimeError):
            pass

    @staticmethod
    def _log_operation_result(
        event: str,
        execution_time_ms: float,
        **context: Any,
    ) -> None:
        """Log a single operation result line with semantic level by latency."""
        payload = {**context, "ms": round(execution_time_ms, 2)}

        level = "debug" if execution_time_ms < 100 else "info"
        getattr(logger, level)(event, **payload)

    @staticmethod
    def _log_trace_operation_result(
        event: str,
        execution_time_ms: float,
        **context: Any,
    ) -> None:
        """Log low-priority periodic operation results on TRACE."""
        payload = {**context, "ms": round(execution_time_ms, 2)}
        logger.trace(event, **payload)

    def get_process_stats(self, pid: int | None = None) -> dict[str, object]:
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
        context: dict[str, object] = {"action": "process_stats", "pid": target_pid}

        def _get_process_info() -> dict[str, object]:
            try:
                process = self._psutil.Process(target_pid)

                # Validate process exists and is accessible
                _ = process.pid  # This will raise if process doesn't exist

            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                logger.warning("bot.system.access.denied.deny", error=str(e), **context)
                return {}

            # Define collectors with better error isolation
            stats_collectors: list[tuple[str, Callable[[], dict[str, object]]]] = [
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

        process_stats_fallback: dict[str, object] = {}
        result, execution_time_ms = self._safe_execute(
            "process stats collection",
            _get_process_info,
            process_stats_fallback,
            timeout=self._DEFAULT_TIMEOUT * 2,  # More time for comprehensive stats
            log_context=context,
        )
        self._log_operation_result(
            "bot.system.process.stats.result",
            execution_time_ms,
            categories=len(result),
            **context,
        )
        return result

    def _collect_stats_concurrently(
        self, collectors: Sequence[tuple[str, Callable[[], dict[str, object]]]]
    ) -> dict[str, object]:
        """
        Collect statistics concurrently using ThreadPoolExecutor with improved error handling.

        Args:
            collectors: Sequence of (name, collector_function) tuples

        Returns:
            Merged dictionary of all collected statistics
        """
        final_stats: dict[str, object] = {}
        context: dict[str, object] = {"action": "concurrent_stats_collection"}
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
                        logger.trace("bot.system.collected.stats.debug", **context)

                except concurrent.futures.TimeoutError:
                    logger.warning(
                        "bot.system.timeout.collecting.warn",
                        timeout_seconds=self._DEFAULT_TIMEOUT,
                        collector=name,
                        **context,
                    )
                except Exception as e:
                    logger.warning(
                        "bot.system.collect.stats.fail",
                        error=str(e),
                        error_type=type(e).__name__,
                        collector=name,
                        **context,
                    )

        logger.trace(
            "bot.system.concurrent.stats.ok",
            collected_categories=successful_collections,
            total_categories=len(collectors),
            **context,
        )
        return final_stats

    def _get_basic_process_info(self, process: psutil.Process) -> dict[str, object]:
        """Get basic process information with safe execution."""

        def _collect() -> dict[str, object]:
            return {
                "pid": process.pid,
                "name": process.name(),
                "status": process.status(),
                "create_time": process.create_time(),
                "parent_pid": getattr(process.parent(), "pid", None)
                if process.parent()
                else None,
            }

        basic_info_fallback: dict[str, object] = {}
        result, _ = self._safe_execute(
            "basic process info",
            _collect,
            basic_info_fallback,
        )
        return result

    def _get_process_cpu_stats(self, process: psutil.Process) -> dict[str, object]:
        """Get CPU-related process statistics with safe execution."""

        def _collect_cpu_stats() -> dict[str, object]:
            cpu_percent = process.cpu_percent(interval=0.0)
            cpu_times = process.cpu_times()

            stats: dict[str, object] = {
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

        cpu_stats_fallback: dict[str, object] = {}
        result, _ = self._safe_execute(
            "CPU stats",
            _collect_cpu_stats,
            cpu_stats_fallback,
        )
        return result

    def _get_process_memory_stats(self, process: psutil.Process) -> dict[str, object]:
        """Get memory-related process statistics with safe execution."""

        def _collect_memory_stats() -> dict[str, object]:
            memory_info = process.memory_info()
            memory_percent = process.memory_percent()

            stats: dict[str, object] = {
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

        memory_stats_fallback: dict[str, object] = {}
        result, _ = self._safe_execute(
            "memory stats",
            _collect_memory_stats,
            memory_stats_fallback,
        )
        return result

    def _get_process_io_stats(self, process: psutil.Process) -> dict[str, object]:
        """Get I/O statistics for the process with safe execution."""

        def _collect_io_stats() -> dict[str, object]:
            io_counters = process.io_counters()
            return {
                "io_read_count": io_counters.read_count,
                "io_write_count": io_counters.write_count,
                "io_read_bytes": set_naturalsize(io_counters.read_bytes),
                "io_write_bytes": set_naturalsize(io_counters.write_bytes),
                "io_read_chars": getattr(io_counters, "read_chars", 0),
                "io_write_chars": getattr(io_counters, "write_chars", 0),
            }

        io_stats_fallback: dict[str, object] = {}
        result, _ = self._safe_execute(
            "I/O stats",
            _collect_io_stats,
            io_stats_fallback,
        )
        return result

    def _get_process_file_stats(self, process: psutil.Process) -> dict[str, object]:
        """Get file descriptor and thread statistics with safe execution."""

        def _collect_file_stats() -> dict[str, object]:
            stats: dict[str, object] = {"num_threads": process.num_threads()}

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

        file_stats_fallback: dict[str, object] = {}
        result, _ = self._safe_execute(
            "file stats",
            _collect_file_stats,
            file_stats_fallback,
        )
        return result

    def _get_process_network_stats(self, process: psutil.Process) -> dict[str, object]:
        """Get network connection statistics with safe execution."""

        def _collect_network_stats() -> dict[str, object]:
            with suppress(psutil.AccessDenied):
                connections = process.net_connections()
                return {
                    "num_connections": len(connections),
                    "connections_by_status": self._count_connections_by_status(
                        connections
                    ),
                }
            return {"num_connections": 0, "connections_by_status": {}}

        network_stats_fallback: dict[str, object] = {}
        result, _ = self._safe_execute(
            "network stats",
            _collect_network_stats,
            network_stats_fallback,
        )
        return result

    def _get_process_context_stats(self, process: psutil.Process) -> dict[str, object]:
        """Get context switch statistics with safe execution."""

        def _collect_context_stats() -> dict[str, object]:
            ctx_switches = process.num_ctx_switches()
            return {
                "ctx_switches_voluntary": ctx_switches.voluntary,
                "ctx_switches_involuntary": ctx_switches.involuntary,
                "ctx_switches_total": ctx_switches.voluntary + ctx_switches.involuntary,
            }

        context_stats_fallback: dict[str, object] = {}
        result, _ = self._safe_execute(
            "context stats",
            _collect_context_stats,
            context_stats_fallback,
        )
        return result

    def _get_process_path_stats(self, process: psutil.Process) -> dict[str, object]:
        """Get working directory and command line information with safe execution."""

        def _collect_path_stats() -> dict[str, object]:
            stats: dict[str, object] = {}

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

        path_stats_fallback: dict[str, object] = {}
        result, _ = self._safe_execute(
            "path stats",
            _collect_path_stats,
            path_stats_fallback,
        )
        return result

    @staticmethod
    def _count_connections_by_status(connections: Sequence[object]) -> dict[str, int]:
        """Count network connections by their status with improved typing."""
        status_counts: dict[str, int] = {}
        for conn in connections:
            status = getattr(conn, "status", "UNKNOWN")
            status_counts[status] = status_counts.get(status, 0) + 1
        return status_counts

    @thread_safe_cache(maxsize=1, ttl_seconds=2.0)  # Cache for 2 seconds
    def get_current_process_health_summary(self) -> dict[str, object]:
        """
        Get a compact health summary for the current process suitable for logging.
        Cached for 2 seconds to avoid excessive system calls.

        Returns:
            Dictionary with key health metrics for logging.
        """
        context: dict[str, object] = {"action": "health_summary"}

        def _get_health_summary() -> dict[str, object]:
            try:
                process = self._psutil.Process()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return {}

            summary: dict[str, object] = {}

            # Essential metrics with error handling
            with suppress(Exception):
                cpu_percent = process.cpu_percent(interval=0.0)
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

        health_summary_fallback: dict[str, object] = {}
        result, execution_time_ms = self._safe_execute(
            "health summary",
            _get_health_summary,
            health_summary_fallback,
            timeout=1.0,  # Quick timeout for health checks
            log_context=context,
        )
        self._log_trace_operation_result(
            "bot.system.process.health.result",
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
        context: dict[str, object] = {"action": "load_average"}

        def _get_load() -> LoadAverage:
            try:
                load_1m, load_5m, load_15m = self._psutil.getloadavg()
                return (float(load_1m), float(load_5m), float(load_15m))
            except (AttributeError, OSError):
                # getloadavg not available on Windows
                return (0.0, 0.0, 0.0)

        result, execution_time_ms = self._safe_execute(
            "load averages",
            _get_load,
            (0.0, 0.0, 0.0),
            log_context=context,
        )
        self._log_operation_result(
            "bot.system.load.average.result",
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
        context: dict[str, object] = {"action": "memory_stats"}

        def _get_memory() -> MemoryStats:
            stats = self._psutil.virtual_memory()
            return {
                "total": set_naturalsize(getattr(stats, "total", 0)),
                "available": set_naturalsize(getattr(stats, "available", 0)),
                "percent": float(getattr(stats, "percent", 0.0)),
                "used": set_naturalsize(getattr(stats, "used", 0)),
                "free": set_naturalsize(getattr(stats, "free", 0)),
                "active": set_naturalsize(getattr(stats, "active", 0)),
                "inactive": set_naturalsize(getattr(stats, "inactive", 0)),
                "cached": set_naturalsize(getattr(stats, "cached", 0)),
                "shared": set_naturalsize(getattr(stats, "shared", 0)),
            }

        zero_size = set_naturalsize(0)
        memory_fallback: MemoryStats = {
            "total": zero_size,
            "available": zero_size,
            "percent": 0.0,
            "used": zero_size,
            "free": zero_size,
            "active": zero_size,
            "inactive": zero_size,
            "cached": zero_size,
            "shared": zero_size,
        }

        result, execution_time_ms = self._safe_execute(
            "memory stats",
            _get_memory,
            memory_fallback,
            log_context=context,
        )
        self._log_operation_result(
            "bot.system.memory.stats.result",
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
        context: dict[str, object] = {"action": "disk_usage"}

        def _get_disk_stats() -> list[DiskStats]:
            stats: list[DiskStats] = []
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

        disk_usage_fallback: list[DiskStats] = []
        result, execution_time_ms = self._safe_execute(
            "disk usage",
            _get_disk_stats,
            disk_usage_fallback,
            log_context=context,
        )
        self._log_operation_result(
            "bot.system.disk.usage.result",
            execution_time_ms,
            partitions_count=len(result),
            **context,
        )
        return result

    @thread_safe_cache(maxsize=1, ttl_seconds=5.0)
    def get_disk_io_stats(self) -> list[DiskIOStats]:
        """Get per-disk I/O counters. Cached for 5 seconds."""
        context: dict[str, object] = {"action": "disk_io_stats"}

        def _get_disk_io() -> list[DiskIOStats]:
            try:
                counters = self._psutil.disk_io_counters(perdisk=True)
            except Exception as e:
                logger.warning("bot.system.fetch.disk.io.fail", error=str(e), **context)
                return []

            if not counters:
                return []

            stats: list[DiskIOStats] = []
            for device_name in sorted(counters):
                device_stats = counters[device_name]
                with suppress(Exception):
                    read_time = int(round(float(getattr(device_stats, "read_time", 0))))
                    write_time = int(
                        round(float(getattr(device_stats, "write_time", 0)))
                    )
                    stats.append(
                        {
                            "device_name": str(device_name),
                            "read_bytes": set_naturalsize(
                                int(getattr(device_stats, "read_bytes", 0))
                            ),
                            "write_bytes": set_naturalsize(
                                int(getattr(device_stats, "write_bytes", 0))
                            ),
                            "read_count": int(getattr(device_stats, "read_count", 0)),
                            "write_count": int(getattr(device_stats, "write_count", 0)),
                            "read_time_ms": read_time,
                            "write_time_ms": write_time,
                        }
                    )
            return stats

        disk_io_fallback: list[DiskIOStats] = []
        result, execution_time_ms = self._safe_execute(
            "disk I/O stats",
            _get_disk_io,
            disk_io_fallback,
            log_context=context,
        )
        self._log_operation_result(
            "bot.system.disk.io.result",
            execution_time_ms,
            devices_count=len(result),
            **context,
        )
        return result

    @thread_safe_cache(maxsize=1, ttl_seconds=5.0)
    def get_swap_memory(self) -> SwapStats:
        """Get swap memory usage statistics. Cached for 5 seconds."""
        context: dict[str, object] = {"action": "swap_memory"}

        def _get_swap() -> SwapStats:
            swap = self._psutil.swap_memory()
            result: SwapStats = {
                "total": set_naturalsize(swap.total),
                "used": set_naturalsize(swap.used),
                "free": set_naturalsize(swap.free),
                "percent": round(swap.percent, 1),
            }
            return result

        zero_size = set_naturalsize(0)
        swap_fallback: SwapStats = {
            "total": zero_size,
            "used": zero_size,
            "free": zero_size,
            "percent": 0.0,
        }
        result, execution_time_ms = self._safe_execute(
            "swap memory",
            _get_swap,
            swap_fallback,
            log_context=context,
        )
        self._log_operation_result(
            "bot.system.swap.memory.result",
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
        context: dict[str, object] = {"action": "sensors_temperatures"}

        def _get_temps() -> list[SensorStats]:
            sensors: list[SensorStats] = []
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

        sensors_fallback: list[SensorStats] = []
        result, execution_time_ms = self._safe_execute(
            "sensor temperatures",
            _get_temps,
            sensors_fallback,
            log_context=context,
        )
        self._log_operation_result(
            "bot.system.sensors.temperature.result",
            execution_time_ms,
            sensors_count=len(result),
            **context,
        )
        return result

    @thread_safe_cache(maxsize=1, ttl_seconds=15.0)
    def get_fan_speeds(self) -> list[FanSpeedStats]:
        """Get fan speeds in RPM. Cached for 15 seconds."""
        context: dict[str, object] = {"action": "fan_speeds"}

        def _get_fans() -> list[FanSpeedStats]:
            try:
                fans = self._psutil.sensors_fans()
            except (AttributeError, OSError):
                return []
            except Exception as e:
                logger.warning("bot.system.fetch.fans.fail", error=str(e), **context)
                return []

            if not fans:
                return []

            fan_stats: list[FanSpeedStats] = []
            for sensor_name, entries in fans.items():
                if not entries:
                    continue
                for fan_entry in entries:
                    with suppress(Exception):
                        current_rpm = getattr(fan_entry, "current", None)
                        if current_rpm is None:
                            continue
                        rpm_value = int(round(float(current_rpm)))
                        if rpm_value < 0:
                            continue
                        label = str(getattr(fan_entry, "label", "")).strip() or "main"
                        fan_stats.append(
                            {
                                "sensor_name": str(sensor_name),
                                "label": label,
                                "rpm": rpm_value,
                            }
                        )

            fan_stats.sort(key=lambda item: (item["sensor_name"], item["label"]))
            return fan_stats

        fans_fallback: list[FanSpeedStats] = []
        result, execution_time_ms = self._safe_execute(
            "fan speeds",
            _get_fans,
            fans_fallback,
            log_context=context,
        )
        self._log_operation_result(
            "bot.system.fans.result",
            execution_time_ms,
            fans_count=len(result),
            **context,
        )
        return result

    @lru_cache(maxsize=1)
    def get_uptime(self) -> str:
        """Get system uptime as a formatted string. Cached until process restart."""
        context: dict[str, object] = {"action": "uptime"}

        def _get_uptime() -> str:
            boot_time = psutil.boot_time()
            uptime = datetime.now() - datetime.fromtimestamp(boot_time)
            return str(uptime).split(".")[0]  # Remove microseconds

        result, execution_time_ms = self._safe_execute(
            "uptime",
            _get_uptime,
            "unknown",
            log_context=context,
        )
        self._log_operation_result(
            "bot.system.uptime.result",
            execution_time_ms,
            uptime=result,
            **context,
        )
        return result

    @thread_safe_cache(maxsize=1, ttl_seconds=5.0)
    def get_process_counts(self) -> ProcessStats:
        """Get process counts by status. Cached for 5 seconds."""
        context: dict[str, object] = {"action": "process_counts"}

        def _get_counts() -> ProcessStats:
            status_counts: dict[str, int] = {
                "running": 0,
                "sleeping": 0,
                "idle": 0,
                "other": 0,
            }

            try:
                for proc in self._psutil.process_iter(["status"]):
                    with suppress(Exception):
                        status = proc.info.get("status", "unknown")
                        if status in status_counts:
                            status_counts[status] += 1
                        else:
                            status_counts["other"] += 1

            except Exception as e:
                logger.warning(
                    "bot.system.iterating.processes.fail", error=str(e), **context
                )
                return {"running": 0, "sleeping": 0, "idle": 0, "total": 0}

            # Calculate total
            total = sum(status_counts.values())
            result: ProcessStats = {
                "running": status_counts["running"],
                "sleeping": status_counts["sleeping"],
                "idle": status_counts["idle"],
                "total": total,
            }
            return result

        process_counts_fallback: ProcessStats = {
            "running": 0,
            "sleeping": 0,
            "idle": 0,
            "total": 0,
        }
        result, execution_time_ms = self._safe_execute(
            "process counts",
            _get_counts,
            process_counts_fallback,
            log_context=context,
        )
        self._log_operation_result(
            "bot.system.process.counts.result",
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
        context: dict[str, object] = {"action": "network_io"}

        def _get_net_io() -> list[NetworkIOStats]:
            stats = self._psutil.net_io_counters()
            if not stats:
                return []

            result: list[NetworkIOStats] = [
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

        network_io_fallback: list[NetworkIOStats] = []
        result, execution_time_ms = self._safe_execute(
            "network I/O",
            _get_net_io,
            network_io_fallback,
            log_context=context,
        )
        first_entry: NetworkIOStats | None = result[0] if result else None
        self._log_operation_result(
            "bot.system.network.io.result",
            execution_time_ms,
            bytes_sent=first_entry.get("bytes_sent") if first_entry else None,
            bytes_recv=first_entry.get("bytes_recv") if first_entry else None,
            **context,
        )
        return result

    @thread_safe_cache(maxsize=1, ttl_seconds=3.0)
    def get_network_connections_summary(self) -> NetworkConnectionsSummary:
        """Get a compact summary of active TCP/UDP connections."""
        context: dict[str, object] = {"action": "network_connections_summary"}

        def _get_connections() -> NetworkConnectionsSummary:
            try:
                connections = self._psutil.net_connections(kind="inet")
            except TypeError:
                # Fallback for psutil implementations without `kind` support.
                connections = self._psutil.net_connections()
            except Exception as e:
                logger.warning(
                    "bot.system.fetch.network.connections.fail",
                    error=str(e),
                    **context,
                )
                return {"total": 0, "tcp": 0, "udp": 0, "statuses": {}}

            statuses: dict[str, int] = {}
            tcp_count = 0
            udp_count = 0

            for connection in connections:
                status = str(getattr(connection, "status", "UNKNOWN") or "UNKNOWN")
                statuses[status] = statuses.get(status, 0) + 1

                conn_type = getattr(connection, "type", None)
                if conn_type == socket.SOCK_STREAM:
                    tcp_count += 1
                elif conn_type == socket.SOCK_DGRAM:
                    udp_count += 1

            return {
                "total": len(connections),
                "tcp": tcp_count,
                "udp": udp_count,
                "statuses": dict(sorted(statuses.items())),
            }

        connections_fallback: NetworkConnectionsSummary = {
            "total": 0,
            "tcp": 0,
            "udp": 0,
            "statuses": {},
        }
        result, execution_time_ms = self._safe_execute(
            "network connections summary",
            _get_connections,
            connections_fallback,
            timeout=self._DEFAULT_TIMEOUT,
            log_context=context,
        )
        self._log_operation_result(
            "bot.system.network.connections.result",
            execution_time_ms,
            total=result.get("total", 0),
            tcp=result.get("tcp", 0),
            udp=result.get("udp", 0),
            **context,
        )
        return result

    @thread_safe_cache(maxsize=1, ttl_seconds=10.0)
    def get_users_info(self) -> list[UserInfo]:
        """Get information about logged-in users. Cached for 10 seconds."""
        context: dict[str, object] = {"action": "users_info"}

        def _get_users() -> list[UserInfo]:
            users: list[UserInfo] = []
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
                logger.warning("bot.system.fetch.users.fail", error=str(e), **context)
            return users

        users_fallback: list[UserInfo] = []
        result, execution_time_ms = self._safe_execute(
            "users info",
            _get_users,
            users_fallback,
            log_context=context,
        )
        self._log_operation_result(
            "bot.system.users.info.result",
            execution_time_ms,
            users_count=len(result),
            **context,
        )
        return result

    @thread_safe_cache(maxsize=1, ttl_seconds=10.0)
    def get_net_interface_stats(self) -> dict[str, NetworkInterfaceStats]:
        """Get network interface statistics. Cached for 10 seconds."""
        context: dict[str, object] = {"action": "network_interfaces"}

        def _get_net_stats() -> dict[str, NetworkInterfaceStats]:
            try:
                if_stats = self._psutil.net_if_stats()
                if_addrs = self._psutil.net_if_addrs()
            except Exception as e:
                logger.warning("bot.system.fetch.network.fail", error=str(e), **context)
                return {}

            result: dict[str, NetworkInterfaceStats] = {}
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

        interface_stats_fallback: dict[str, NetworkInterfaceStats] = {}
        result, execution_time_ms = self._safe_execute(
            "network interface stats",
            _get_net_stats,
            interface_stats_fallback,
            log_context=context,
        )
        active_interfaces = 0
        for interface_stats in result.values():
            if interface_stats["is_up"]:
                active_interfaces += 1
        self._log_operation_result(
            "bot.system.network.interfaces.result",
            execution_time_ms,
            total_interfaces=len(result),
            active_interfaces=active_interfaces,
            **context,
        )
        return result

    @thread_safe_cache(maxsize=1, ttl_seconds=5.0)
    def get_cpu_frequency(self) -> CPUFrequencyStats:
        """Get CPU frequency information. Cached for 5 seconds."""
        context: dict[str, object] = {"action": "cpu_frequency"}

        def _get_cpu_freq() -> CPUFrequencyStats:
            try:
                freq = self._psutil.cpu_freq()
                if freq is None:
                    return {"current_freq": 0.0, "min_freq": 0.0, "max_freq": 0.0}

                result: CPUFrequencyStats = {
                    "current_freq": round(freq.current, 1) if freq.current else 0.0,
                    "min_freq": round(freq.min, 1) if freq.min else 0.0,
                    "max_freq": round(freq.max, 1) if freq.max else 0.0,
                }
                return result

            except (AttributeError, OSError):
                # CPU frequency not available on this system
                return {"current_freq": 0.0, "min_freq": 0.0, "max_freq": 0.0}

        cpu_frequency_fallback: CPUFrequencyStats = {
            "current_freq": 0.0,
            "min_freq": 0.0,
            "max_freq": 0.0,
        }
        result, execution_time_ms = self._safe_execute(
            "CPU frequency",
            _get_cpu_freq,
            cpu_frequency_fallback,
            log_context=context,
        )
        self._log_operation_result(
            "bot.system.cpu.frequency.result",
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
        """
        context: dict[str, object] = {"action": "cpu_usage"}

        def _get_cpu_usage() -> CPUUsageStats:
            with self._cpu_usage_lock:
                cached_snapshot = self._cpu_usage_snapshot
            if cached_snapshot is not None:
                return {
                    "cpu_percent": float(cached_snapshot["cpu_percent"]),
                    "cpu_percent_per_core": list(
                        cached_snapshot["cpu_percent_per_core"]
                    ),
                }

            cpu_per_core_raw = self._psutil.cpu_percent(interval=0.0, percpu=True)
            cpu_per_core = [
                round(float(core), 1)
                for core in cpu_per_core_raw
                if isinstance(core, (int, float))
            ]
            if cpu_per_core and any(core > 0.0 for core in cpu_per_core):
                cpu_percent = round(sum(cpu_per_core) / len(cpu_per_core), 1)
            else:
                cpu_percent_raw = self._psutil.cpu_percent(interval=0.0)
                cpu_percent = (
                    round(float(cpu_percent_raw), 1)
                    if isinstance(cpu_percent_raw, (int, float))
                    else 0.0
                )

            snapshot: CPUUsageStats = {
                "cpu_percent": cpu_percent,
                "cpu_percent_per_core": cpu_per_core,
            }
            with self._cpu_usage_lock:
                self._cpu_usage_snapshot = snapshot
            return snapshot

        cpu_usage_fallback: CPUUsageStats = {
            "cpu_percent": 0.0,
            "cpu_percent_per_core": [],
        }
        result, execution_time_ms = self._safe_execute(
            "CPU usage",
            _get_cpu_usage,
            cpu_usage_fallback,
            timeout=1.0,
            log_context=context,
        )
        self._log_operation_result(
            "bot.system.cpu.usage.result",
            execution_time_ms,
            overall_cpu=f"{result.get('cpu_percent', 0.0):.1f}%",
            cores_count=len(result.get("cpu_percent_per_core", [])),
            **context,
        )
        return result

    @thread_safe_cache(maxsize=1, ttl_seconds=3.0)
    def get_cpu_times_percent(self) -> CPUTimesPercentStats:
        """Get CPU time distribution in percentages."""
        context: dict[str, object] = {"action": "cpu_times_percent"}

        def _get_cpu_times_percent() -> CPUTimesPercentStats:
            try:
                cpu_times = self._psutil.cpu_times_percent(interval=0.0)
            except (AttributeError, OSError):
                return {
                    "user": 0.0,
                    "system": 0.0,
                    "idle": 0.0,
                    "iowait": 0.0,
                    "irq": 0.0,
                    "softirq": 0.0,
                }

            return {
                "user": round(float(getattr(cpu_times, "user", 0.0)), 1),
                "system": round(float(getattr(cpu_times, "system", 0.0)), 1),
                "idle": round(float(getattr(cpu_times, "idle", 0.0)), 1),
                "iowait": round(float(getattr(cpu_times, "iowait", 0.0)), 1),
                "irq": round(float(getattr(cpu_times, "irq", 0.0)), 1),
                "softirq": round(float(getattr(cpu_times, "softirq", 0.0)), 1),
            }

        cpu_times_fallback: CPUTimesPercentStats = {
            "user": 0.0,
            "system": 0.0,
            "idle": 0.0,
            "iowait": 0.0,
            "irq": 0.0,
            "softirq": 0.0,
        }
        result, execution_time_ms = self._safe_execute(
            "CPU times percent",
            _get_cpu_times_percent,
            cpu_times_fallback,
            log_context=context,
        )
        self._log_operation_result(
            "bot.system.cpu.times.result",
            execution_time_ms,
            user=result.get("user"),
            system=result.get("system"),
            idle=result.get("idle"),
            iowait=result.get("iowait"),
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

        def _get_top_processes() -> tuple[list[TopProcess], int, int]:
            processes: list[TopProcess] = []
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
                    "bot.system.iterating.processes.fail", error=str(e), **context
                )
                return [], 0, excluded_processes

            # Sort by combined CPU and memory usage (weighted average)
            top_processes = heapq.nlargest(
                count,
                processes,
                key=lambda p: p["cpu_percent"] * 0.6 + p["memory_percent"] * 0.4,
            )

            return top_processes, len(processes), excluded_processes

        top_processes_fallback: tuple[list[TopProcess], int, int] = ([], 0, 0)
        result, execution_time_ms = self._safe_execute(
            "top processes",
            _get_top_processes,
            top_processes_fallback,
            timeout=3.0,  # Allow more time for process iteration
            log_context=context,
        )
        top_processes, processes_analyzed, excluded_processes = result
        top_cpu = f"{top_processes[0]['cpu_percent']:.1f}%" if top_processes else "0.0%"
        top_memory = (
            f"{top_processes[0]['memory_percent']:.1f}%" if top_processes else "0.0%"
        )
        self._log_operation_result(
            "bot.system.top.processes.result",
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
        context: dict[str, object] = {"action": "cpu_count"}
        result, execution_time_ms = self._safe_execute(
            "CPU count",
            lambda: self._psutil.cpu_count(logical=True) or 1,
            1,
            log_context=context,
        )
        self._log_operation_result(
            "bot.system.cpu.count.result",
            execution_time_ms,
            cpu_cores=result,
            **context,
        )
        return result

    @lru_cache(maxsize=1)
    def get_cpu_count_physical(self) -> int:
        """Get the number of physical CPU cores. Cached permanently."""
        context: dict[str, object] = {"action": "cpu_count_physical"}
        result, execution_time_ms = self._safe_execute(
            "CPU physical core count",
            lambda: self._psutil.cpu_count(logical=False) or 1,
            1,
            log_context=context,
        )
        self._log_operation_result(
            "bot.system.cpu.count.physical.result",
            execution_time_ms,
            physical_cores=result,
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

        logger.info("bot.system.all.caches.info")

    def get_system_summary(self) -> dict[str, object]:
        """
        Get a comprehensive system summary with all major metrics.

        Returns:
            Dictionary with system overview including CPU, memory, disk, and process info.
        """
        context: dict[str, object] = {"action": "system_summary"}

        def _collect_summary() -> dict[str, object]:
            summary: dict[str, object] = {}
            collectors: list[tuple[str, Callable[[], object]]] = [
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
                        "bot.system.collect.summary.fail",
                        error=str(e),
                        **context,
                    )

            return summary

        summary_fallback: dict[str, object] = {}
        result, execution_time_ms = self._safe_execute(
            "system summary",
            _collect_summary,
            summary_fallback,
            log_context=context,
        )
        self._log_operation_result(
            "bot.system.summary.result",
            execution_time_ms,
            categories=len(result),
            **context,
        )
        return result
