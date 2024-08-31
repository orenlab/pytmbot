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
                key: set_naturalsize(getattr(memory_stats, key))
                if key != 'percent' else memory_stats.percent
                for key in ['total', 'available', 'percent', 'used', 'free', 'active', 'inactive', 'cached', 'shared']
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
                fs_current.append({
                    'device_name': fs.device,
                    'fs_type': fs.fstype,
                    'mnt_point': fs.mountpoint.replace('\u00A0', ' '),
                    'size': set_naturalsize(disk_usage.total),
                    'used': set_naturalsize(disk_usage.used),
                    'free': set_naturalsize(disk_usage.free),
                    'percent': disk_usage.percent
                })
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
                'total': set_naturalsize(swap.total),
                'used': set_naturalsize(swap.used),
                'free': set_naturalsize(swap.free),
                'percent': swap.percent,
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
                sensors_current.append({
                    'sensor_name': sensor_name,
                    'sensor_value': temperature_stats[0][1],
                })
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
        uptime = str(uptime_raw).split('.')[0]
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
                status: sum(1 for proc in self.psutil.process_iter() if proc.status() == status)
                for status in ['running', 'sleeping', 'idle']
            }
            process_counts['total'] = sum(process_counts.values())
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
            net_io_stat_current = [{
                'bytes_sent': set_naturalsize(net_io_stat.bytes_sent),
                'bytes_recv': set_naturalsize(net_io_stat.bytes_recv),
                'packets_sent': net_io_stat.packets_sent,
                'packets_recv': net_io_stat.packets_recv,
                'err_in': net_io_stat.errin,
                'err_out': net_io_stat.errout,
                'drop_in': net_io_stat.dropin,
                'drop_out': net_io_stat.dropout
            }]
            bot_logger.debug(f"Network I/O stats: {net_io_stat_current}")
            return net_io_stat_current
        except AttributeError as e:
            bot_logger.error(f"Failed to retrieve network I/O statistics: {e}")
            return []
