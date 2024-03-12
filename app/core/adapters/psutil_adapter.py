#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from _pydatetime import datetime

import psutil
import app.utilities.utilities as utilities


class PsutilAdapter:
    """Class to adapt psutil to pyTMBot"""

    def __init__(self):
        self.psutil = psutil
        self.fs_current: None = None
        self.sensors_current = []
        self.format_bytes = utilities.format_bytes
        self.memory_stat: None = None
        self.fs_stats: None = None
        self.fs_usage: None = None
        self.memory_current: None = None
        self.sensors_stat: None = None
        self.sw_current: None = None

    @staticmethod
    def get_load_average():
        """Get the load average"""
        return psutil.getloadavg()

    @staticmethod
    def get_cpu_count():
        """Get cpu count"""
        return psutil.cpu_count()

    def get_memory(self):
        """Get current memory usage"""
        try:
            self.memory_current = ''  # Unset attr
            self.memory_stat = self.psutil.virtual_memory()
            self.memory_current = {
                'total': self.format_bytes(self.memory_stat.total),
                'available': self.format_bytes(self.memory_stat.available),
                'percent': self.memory_stat.percent,
                'used': self.format_bytes(self.memory_stat.used),
                'free': self.format_bytes(self.memory_stat.free),
                'active': self.format_bytes(self.memory_stat.active),
                'inactive': self.format_bytes(self.memory_stat.inactive),
                'cached': self.format_bytes(self.memory_stat.cached),
                'shared': self.format_bytes(self.memory_stat.shared),
            }
            return self.memory_current
        except PermissionError as _err:
            raise PermissionError('Error get memory info') from _err
        finally:
            self.memory_current: ''

    def get_disk_usage(self):
        """Get partition usage"""
        try:
            self.fs_current = []  # Unset attr
            self.fs_stats = psutil.disk_partitions(all=False)
            for fs in self.fs_stats:
                try:
                    self.fs_usage = self.psutil.disk_usage(fs.mountpoint)
                except OSError:
                    continue
                self.fs_current.append({
                    'device_name': fs.device,
                    'fs_type': fs.fstype,
                    'mnt_point': fs.mountpoint.replace(u'\u00A0', ' '),
                    'size': self.format_bytes(self.fs_usage.total),
                    'used': self.format_bytes(self.fs_usage.used),
                    'free': self.format_bytes(self.fs_usage.free),
                    'percent': self.fs_usage.percent
                }, )
            return self.fs_current
        except PermissionError as _err:
            raise PermissionError('FS: Permission denied') from _err
        except KeyError as _err:
            raise PermissionError('FS: Key error') from _err
        finally:
            self.fs_current = ''

    def get_swap_memory(self):
        """Get swap memory usage"""
        try:
            self.sw_current = []
            swap = psutil.swap_memory()
            self.sw_current = {
                'total': self.format_bytes(swap.total),
                'used': self.format_bytes(swap.used),
                'free': self.format_bytes(swap.free),
                'percent': swap.percent,
            }
            return self.sw_current
        except PermissionError as _err:
            raise PermissionError('SW: cannot get swap info') from _err
        finally:
            self.sw_current: ''

    def get_sensors_temperatures(self):
        """Get sensors temperatures"""
        try:
            self.sensors_current = []
            self.sensors_stat = self.psutil.sensors_temperatures()
            for key, value in self.sensors_stat.items():
                self.sensors_current.append({
                    'sensor_name': key,
                    'sensor_value': value[0][1],
                })
            return self.sensors_current
        except AttributeError:
            raise AttributeError(
                'Cannot get sensors temperatures'
            )
        except KeyError as _err:
            raise PermissionError('Sensors: Key error') from _err
        finally:
            self.sensors_current: ''

    @staticmethod
    def get_sensors_fans():
        """Get sensors fans speed"""
        return psutil.sensors_fans()

    @staticmethod
    def get_uptime():
        """Get system uptime"""
        uptime_raw = datetime.now() - datetime.fromtimestamp(psutil.boot_time())
        uptime = str(uptime_raw).split('.')[0]
        return uptime
