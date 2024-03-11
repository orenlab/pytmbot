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
        self.fs_current = []
        self.sensors_current = []
        self.format_bytes = utilities.format_bytes

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
            memory_stat = psutil.virtual_memory()
            memory_current = {
                'total': self.format_bytes(memory_stat.total),
                'available': self.format_bytes(memory_stat.available),
                'percent': memory_stat.percent,
                'used': self.format_bytes(memory_stat.used),
                'free': self.format_bytes(memory_stat.free),
                'active': self.format_bytes(memory_stat.active),
                'inactive': self.format_bytes(memory_stat.inactive),
                'cached': self.format_bytes(memory_stat.cached),
                'shared': self.format_bytes(memory_stat.shared),
            }
            return memory_current
        except psutil.PermissionError as _err:
            raise PermissionError('Error get memory info') from _err

    def get_disk_usage(self):
        """Get partition usage"""
        try:
            fs_stats = psutil.disk_partitions(all=False)
            for fs in fs_stats:
                try:
                    fs_usage = self.psutil.disk_usage(fs.mountpoint)
                except OSError:
                    continue
                self.fs_current.append({
                    'device_name': fs.device,
                    'fs_type': fs.fstype,
                    'mnt_point': fs.mountpoint.replace(u'\u00A0', ' '),
                    'size': self.format_bytes(fs_usage.total),
                    'used': self.format_bytes(fs_usage.used),
                    'free': self.format_bytes(fs_usage.free),
                    'percent': fs_usage.percent
                }, )
            return self.fs_current
        except PermissionError as _err:
            raise PermissionError('FS: Permission denied') from _err
        except KeyError as _err:
            raise PermissionError('FS: Key error') from _err

    def get_swap_memory(self):
        """Get swap memory usage"""
        swap = psutil.swap_memory()
        sw_current = {
            'total': self.format_bytes(swap.total),
            'used': self.format_bytes(swap.used),
            'free': self.format_bytes(swap.free),
            'percent': swap.percent,
        }
        return sw_current

    def get_sensors_temperatures(self):
        """Get sensors temperatures"""
        try:
            sensors_stat = self.psutil.sensors_temperatures()
            for key, value in sensors_stat.items():
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

    @staticmethod
    def get_sensors_fans():
        """Get sensors fans speed"""
        return psutil.sensors_fans()

    @staticmethod
    def get_uptime():
        """Get system uptime"""
        all_pid = psutil.pids()
        first_system_pid = all_pid[0]
        pid_info = psutil.Process(first_system_pid)
        first_pid_run = pid_info.create_time()
        uptime_raw = datetime.now() - datetime.fromtimestamp(first_pid_run)
        uptime = str(uptime_raw).split('.')[0]
        return uptime
