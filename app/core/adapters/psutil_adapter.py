#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from datetime import datetime

import psutil
from humanize import naturalsize

from app.core.logs import bot_logger


class PsutilAdapter:
    """Class to adapt psutil to pyTMBot"""

    def __init__(self):
        """Init psutil adapter class"""
        self.psutil = psutil
        self.fs_current: None = None
        self.sensors_current = []
        self.memory_stat: None = None
        self.fs_stats: None = None
        self.fs_usage: None = None
        self.memory_current: None = None
        self.sensors_stat: None = None
        self.sw_current: None = None
        self.process_count = {}
        self.sleeping: int = 0
        self.running: int = 0
        self.idle: int = 0
        self.net_io_stat = None

    @staticmethod
    def get_load_average():
        """Get the load average"""
        bot_logger.debug("Load Average stats is received")
        return psutil.getloadavg()

    @staticmethod
    def get_cpu_count():
        """Get cpu count"""
        bot_logger.debug("CPU count is received")
        return psutil.cpu_count()

    def get_memory(self):
        """Get current memory usage"""
        try:
            self.memory_current = ''  # Unset attr
            self.memory_stat = self.psutil.virtual_memory()
            self.memory_current = {
                'total': naturalsize(self.memory_stat.total, binary=True),
                'available': naturalsize(self.memory_stat.available, binary=True),
                'percent': self.memory_stat.percent,
                'used': naturalsize(self.memory_stat.used, binary=True),
                'free': naturalsize(self.memory_stat.free, binary=True),
                'active': naturalsize(self.memory_stat.active, binary=True),
                'inactive': naturalsize(self.memory_stat.inactive, binary=True),
                'cached': naturalsize(self.memory_stat.cached, binary=True),
                'shared': naturalsize(self.memory_stat.shared, binary=True),
            }
            bot_logger.debug(f"Memory stats is received: {self.memory_current}")
            return self.memory_current
        except (PermissionError, ValueError) as e:
            bot_logger.error(f"Failed at @{__name__}: {e}")

    def get_disk_usage(self):
        """Get partition usage"""
        try:
            self.fs_current = []  # Unset attr
            self.fs_stats = psutil.disk_partitions(all=False)
            bot_logger.debug(f"Partitions stats is received: {self.fs_stats}")
            for fs in self.fs_stats:
                try:
                    self.fs_usage = self.psutil.disk_usage(fs.mountpoint)
                except OSError:
                    continue
                self.fs_current.append({
                    'device_name': fs.device,
                    'fs_type': fs.fstype,
                    'mnt_point': fs.mountpoint.replace(u'\u00A0', ' '),
                    'size': naturalsize(self.fs_usage.total, binary=True),
                    'used': naturalsize(self.fs_usage.used, binary=True),
                    'free': naturalsize(self.fs_usage.free, binary=True),
                    'percent': self.fs_usage.percent
                },
                )
            bot_logger.debug(f"File system stats is received: {self.fs_current}")
            return self.fs_current
        except (PermissionError, KeyError) as e:
            bot_logger.error(f"Failed at @{__name__}: {e}")

    def get_swap_memory(self):
        """Get swap memory usage"""
        try:
            self.sw_current = []  # unset attr
            swap = psutil.swap_memory()
            self.sw_current = {
                'total': naturalsize(swap.total, binary=True),
                'used': naturalsize(swap.used, binary=True),
                'free': naturalsize(swap.free, binary=True),
                'percent': swap.percent,
            }
            bot_logger.debug(f"Swap memory stats is received: {self.sw_current}")
            return self.sw_current
        except PermissionError as e:
            bot_logger.error(f"Failed at @{__name__}: {e}")

    def get_sensors_temperatures(self):
        """Get sensors temperatures"""
        try:
            self.sensors_current = []  # unset attr
            self.sensors_stat = self.psutil.sensors_temperatures()
            bot_logger.debug("Sensors stats is received")
            if not self.sensors_stat:
                bot_logger.debug(f"Error receiving data from temperature sensors")
            else:
                for key, value in self.sensors_stat.items():
                    self.sensors_current.append({
                        'sensor_name': key,
                        'sensor_value': value[0][1],
                    })
            bot_logger.debug(f"Sensors stats append: {self.sensors_current}")
            return self.sensors_current
        except (AttributeError, KeyError, ValueError) as e:
            bot_logger.error(f"Failed at @{__name__}: {e}")

    @staticmethod
    def get_sensors_fans():
        """Get sensors fans speed"""
        return psutil.sensors_fans()

    @staticmethod
    def get_uptime():
        """
        Get system uptime

        Returns:
            object: Uptime

        """
        uptime_raw = datetime.now() - datetime.fromtimestamp(psutil.boot_time())
        uptime = str(uptime_raw).split('.')[0]
        bot_logger.debug(f"Uptime stats is received: {uptime}")
        return uptime

    def get_process_counts(self):
        """
        Get process count information

        Returns:
            object: Process count

        """
        try:
            self.sleeping = 0  # unset attr
            self.running = 0  # unset attr
            self.idle = 0  # unset attr
            for proc in self.psutil.process_iter():
                match proc.status():
                    case "sleeping":
                        self.sleeping += 1
                    case "running":
                        self.running += 1
                    case "idle":
                        self.idle += 1
            bot_logger.debug("Proc iterate stats done")
            self.process_count = {
                'running': self.running,
                'sleeping': self.sleeping,
                'idle': self.idle,
                'total': self.sleeping + self.running + self.idle
            }
            bot_logger.debug(f"Proc stats is received: {self.process_count}")
            return self.process_count
        except AttributeError as e:
            bot_logger.error(f"Failed at @{__name__}: {e}")

    def get_net_io_counters(self):
        try:
            net_io_stat_current = []
            self.net_io_stat = self.psutil.net_io_counters()
            bot_logger.debug("Network IO stat recv")
            net_io_stat_current.append({
                'bytes_sent': naturalsize(self.net_io_stat.bytes_recv, binary=True),
                'bytes_recv': naturalsize(self.net_io_stat.packets_recv, binary=True),
                'packets_sent': self.net_io_stat.packets_sent,
                'packets_recv': self.net_io_stat.packets_recv,
                'err_in': self.net_io_stat.errin,
                'err_out': self.net_io_stat.errout,
                'drop_in': self.net_io_stat.dropin,
                'drop_out': self.net_io_stat.dropout
            })
            bot_logger.debug(f"Network IO stat append done: {net_io_stat_current}")
            return net_io_stat_current
        except AttributeError as e:
            bot_logger.error(f"Failed at @{__name__}: {e}")
