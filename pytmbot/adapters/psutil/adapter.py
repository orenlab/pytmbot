from datetime import datetime
from typing import Tuple, List, Dict, Union

try:
    import psutil
except ImportError:
    raise ModuleNotFoundError("psutil library is not installed. Please install it.")

from pytmbot.logs import bot_logger
from pytmbot.utils.utilities import set_naturalsize


class PsutilAdapter:
    """
    A class that wraps the psutil library for easier usage.
    Provides methods to retrieve various system statistics using the psutil library.
    """

    def __init__(self):
        """
        Initialize the PsutilAdapter class.
        """
        self.psutil = psutil

    @staticmethod
    def get_load_average() -> Tuple[float, float, float]:
        """
        Get the load average for the last 1 minute, 5 minutes, and 15 minutes.

        Returns:
            Tuple[float, float, float]: The load average.
        """
        bot_logger.debug("Retrieving load average...")
        load_average = psutil.getloadavg()
        return load_average

    def get_memory(self) -> Dict[str, Union[str, int]]:
        """
        Retrieve current memory usage statistics.

        Returns:
            Dict[str, Union[str, int]]: Memory usage statistics.
        """
        try:
            memory_stats = self.psutil.virtual_memory()
            memory_current = {
                key: (
                    set_naturalsize(getattr(memory_stats, key))
                    if key != "percent"
                    else memory_stats.percent
                )
                for key in [
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
            }
            return memory_current
        except (PermissionError, ValueError) as e:
            bot_logger.error(f"Failed to retrieve memory statistics: {e}")
            return {}

    def get_disk_usage(self) -> List[Dict[str, Union[str, float]]]:
        """
        Get partition usage statistics.

        Returns:
            List[Dict[str, Union[str, float]]]: Usage statistics for each partition.
        """
        try:
            fs_stats = self.psutil.disk_partitions(all=False)
            fs_current = []
            for fs in fs_stats:
                disk_usage = self.psutil.disk_usage(fs.mountpoint)
                fs_current.append(
                    {
                        "device_name": fs.device,
                        "fs_type": fs.fstype,
                        "mnt_point": fs.mountpoint.replace("\u00A0", " "),
                        "size": set_naturalsize(disk_usage.total),
                        "used": set_naturalsize(disk_usage.used),
                        "free": set_naturalsize(disk_usage.free),
                        "percent": disk_usage.percent,
                    }
                )
            bot_logger.debug(f"File system stats: {fs_current}")
            return fs_current
        except (PermissionError, KeyError) as e:
            bot_logger.error(f"Failed to retrieve disk usage statistics: {e}")
            return []

    def get_swap_memory(self) -> Dict[str, Union[str, int]]:
        """
        Get swap memory usage.

        Returns:
            Dict[str, Union[str, int]]: Swap memory usage statistics.
        """
        try:
            swap = self.psutil.swap_memory()
            sw_current = {
                "total": set_naturalsize(swap.total),
                "used": set_naturalsize(swap.used),
                "free": set_naturalsize(swap.free),
                "percent": swap.percent,
            }
            bot_logger.debug(f"Swap memory stats: {sw_current}")
            return sw_current
        except PermissionError as e:
            bot_logger.error(f"Failed to retrieve swap memory statistics: {e}")
            return {}

    def get_sensors_temperatures(self) -> List[Dict[str, Union[str, float]]]:
        """
        Get sensors temperatures.

        Returns:
            List[Dict[str, Union[str, float]]]: Sensor temperatures.
        """
        sensors_current: List[Dict[str, Union[str, float]]] = []
        try:
            sensors_stat = self.psutil.sensors_temperatures()
            if not sensors_stat:
                bot_logger.error("No temperature sensors data available")
            for sensor_name, temperature_stats in sensors_stat.items():
                sensors_current.append(
                    {
                        "sensor_name": sensor_name,
                        "sensor_value": temperature_stats[0][1],
                    }
                )
            bot_logger.debug(f"Sensors stats: {sensors_current}")
            return sensors_current
        except (AttributeError, KeyError, ValueError) as e:
            bot_logger.error(f"Failed to retrieve sensors temperatures: {e}")
            return []

    @staticmethod
    def get_uptime() -> str:
        """
        Get the system uptime in the format 'X days, Y hours, Z minutes, A seconds'.

        Returns:
            str: The uptime.
        """
        uptime_raw = datetime.now() - datetime.fromtimestamp(psutil.boot_time())
        uptime = str(uptime_raw).split(".")[0]
        bot_logger.debug(f"Uptime: {uptime}")
        return uptime

    def get_process_counts(self) -> Dict[str, int]:
        """
        Get the counts of running, sleeping, and idle processes.

        Returns:
            Dict[str, int]: Process counts.
        """
        try:
            process_counts = {
                status: sum(
                    1 for proc in self.psutil.process_iter() if proc.status() == status
                )
                for status in ["running", "sleeping", "idle"]
            }
            process_counts["total"] = sum(process_counts.values())
            bot_logger.debug(f"Process counts: {process_counts}")
            return process_counts
        except AttributeError as e:
            bot_logger.error(f"Failed to retrieve process counts: {e}")
            return {}

    def get_net_io_counters(self) -> List[Dict[str, Union[str, int]]]:
        """
        Retrieves network I/O statistics.

        Returns:
            List[Dict[str, Union[str, int]]]: Network I/O statistics.
        """
        try:
            net_io_stat = self.psutil.net_io_counters()
            net_io_stat_current = [
                {
                    "bytes_sent": set_naturalsize(net_io_stat.bytes_sent),
                    "bytes_recv": set_naturalsize(net_io_stat.bytes_recv),
                    "packets_sent": net_io_stat.packets_sent,
                    "packets_recv": net_io_stat.packets_recv,
                    "err_in": net_io_stat.errin,
                    "err_out": net_io_stat.errout,
                    "drop_in": net_io_stat.dropin,
                    "drop_out": net_io_stat.dropout,
                }
            ]
            bot_logger.debug(f"Network I/O stats: {net_io_stat_current}")
            return net_io_stat_current
        except AttributeError as e:
            bot_logger.error(f"Failed to retrieve network I/O statistics: {e}")
            return []

    def get_users_info(self) -> List[Dict[str, Union[str, float]]]:
        """
        Get the list of users currently logged into the system.

        Returns:
            List[Dict[str, Union[str, float]]]: List of users with login time.
        """
        users_info = []
        try:
            users = self.psutil.users()
            for user in users:
                users_info.append(
                    {
                        "username": user.name,
                        "terminal": user.terminal,
                        "host": user.host,
                        "started": user.started,
                    }
                )
            bot_logger.debug(f"Retrieved {len(users_info)} users currently logged in")
        except Exception as e:
            bot_logger.error(f"Failed to retrieve users information: {e}")
        return users_info

    def get_net_interface_stats(self) -> Dict[str, Dict[str, Union[int, str]]]:
        """
        Get detailed network statistics per interface.

        Returns:
            Dict[str, Dict[str, Union[int, str]]]: Network statistics per interface.
        """
        net_if_stats = self.psutil.net_if_stats()
        net_if_addrs = self.psutil.net_if_addrs()

        net_stats = {}
        for interface, stats in net_if_stats.items():
            net_stats[interface] = {
                "is_up": stats.isup,
                "speed": stats.speed,
                "duplex": stats.duplex,
                "mtu": stats.mtu,
                "ip_address": (
                    net_if_addrs[interface][0].address
                    if interface in net_if_addrs
                    else "N/A"
                ),
            }
        bot_logger.debug(f"Network interface stats: {net_stats}")
        return net_stats

    def get_cpu_frequency(self) -> Dict[str, float]:
        """
        Get the CPU frequency (current, min, max).

        Returns:
            Dict[str, float]: CPU frequency statistics.
        """
        cpu_freq = self.psutil.cpu_freq()
        cpu_freq_stats = {
            "current_freq": cpu_freq.current,
            "min_freq": cpu_freq.min,
            "max_freq": cpu_freq.max,
        }
        bot_logger.debug(f"CPU frequency stats: {cpu_freq_stats}")
        return cpu_freq_stats

    def get_cpu_usage(self) -> Dict[str, Union[float, List[float]]]:
        """
        Get CPU usage statistics.

        Returns:
            Dict[str, Union[float, List[float]]]: CPU usage statistics.
        """
        cpu_stats = {
            "cpu_percent": self.psutil.cpu_percent(interval=1),
            "cpu_percent_per_core": self.psutil.cpu_percent(interval=1, percpu=True),
        }
        bot_logger.debug(f"CPU usage stats: {cpu_stats}")
        return cpu_stats
