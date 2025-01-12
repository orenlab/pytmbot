from contextlib import suppress
from datetime import datetime

import psutil

from pytmbot.adapters.psutil.types import LoadAverage, MemoryStats, DiskStats, SwapStats, SensorStats, ProcessStats, \
    NetworkIOStats, UserInfo, NetworkInterfaceStats, CPUFrequencyStats, CPUUsageStats
from pytmbot.logs import Logger
from pytmbot.utils import set_naturalsize

# Type definitions


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
                extra={"result": result, **log_context}
            )
            return result
        except Exception as e:
            logger.error(
                f"Failed to retrieve {operation}",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "operation": operation,
                    **log_context
                }
            )
            return fallback

    def get_load_average(self) -> LoadAverage:
        """Get system load averages."""
        return self._safe_execute(
            "load averages",
            self._psutil.getloadavg,
            (0.0, 0.0, 0.0)
        )

    def get_memory(self) -> MemoryStats:
        """Get memory statistics with natural size formatting."""
        memory_attrs = [
            "total", "available", "percent", "used", "free",
            "active", "inactive", "cached", "shared"
        ]

        def _get_memory():
            stats = self._psutil.virtual_memory()
            return {
                attr: (
                    set_naturalsize(getattr(stats, attr))
                    if attr != "percent" else getattr(stats, attr)
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
                    stats.append({
                        "device_name": fs.device,
                        "fs_type": fs.fstype,
                        "mnt_point": fs.mountpoint.replace("\u00A0", " "),
                        "size": set_naturalsize(usage.total),
                        "used": set_naturalsize(usage.used),
                        "free": set_naturalsize(usage.free),
                        "percent": usage.percent
                    })
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
                "percent": swap.percent
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
                    sensors.append({
                        "sensor_name": name,
                        "sensor_value": stats[0][1]
                    })
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
                status: sum(1 for proc in self._psutil.process_iter(['status'])
                            if proc.info['status'] == status)
                for status in ('running', 'sleeping', 'idle')
            }
            counts['total'] = sum(counts.values())
            return counts

        return self._safe_execute("process counts", _get_counts, {})

    def get_net_io_counters(self) -> list[NetworkIOStats]:
        """Get network I/O statistics."""

        def _get_net_io():
            stats = self._psutil.net_io_counters()
            return [{
                "bytes_sent": set_naturalsize(stats.bytes_sent),
                "bytes_recv": set_naturalsize(stats.bytes_recv),
                "packets_sent": stats.packets_sent,
                "packets_recv": stats.packets_recv,
                "err_in": stats.errin,
                "err_out": stats.errout,
                "drop_in": stats.dropin,
                "drop_out": stats.dropout
            }]

        return self._safe_execute("network I/O", _get_net_io, [])

    def get_users_info(self) -> list[UserInfo]:
        """Get information about logged-in users."""

        def _get_users():
            return [{
                "username": user.name,
                "terminal": user.terminal,
                "host": user.host,
                "started": user.started
            } for user in self._psutil.users()]

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
                    )
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
                "max_freq": freq.max
            }

        return self._safe_execute("CPU frequency", _get_cpu_freq, {})

    def get_cpu_usage(self) -> CPUUsageStats:
        """Get CPU usage statistics."""

        def _get_cpu_usage():
            return {
                "cpu_percent": self._psutil.cpu_percent(interval=1),
                "cpu_percent_per_core": self._psutil.cpu_percent(interval=1, percpu=True)
            }

        return self._safe_execute("CPU usage", _get_cpu_usage, {
            "cpu_percent": 0.0,
            "cpu_percent_per_core": []
        })
