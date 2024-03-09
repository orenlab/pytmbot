#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
import psutil


class PsutilAdapter:
    """Class to psutil communication with Telegram bot"""

    def __init__(self):
        self.psutil = psutil
        self.fs_current = []

    @staticmethod
    def get_load_average():
        """Get the load average"""
        data = psutil.getloadavg()
        return data

    @staticmethod
    def get_cpu_count():
        """Get cpu count"""
        return psutil.cpu_count()

    @staticmethod
    def get_memory():
        """Get current memory usage"""
        data = psutil.virtual_memory()
        return data

    @staticmethod
    def get_swap_memory():
        """Get swap memory usage"""
        return psutil.swap_memory()

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
                    'size': fs_usage.total,
                    'used': fs_usage.used,
                    'free': fs_usage.free,
                    'percent': fs_usage.percent
                }, )

            return self.fs_current
        except PermissionError as _err:
            raise PermissionError('FS: Permission denied') from _err
        except KeyError as _err:
            raise PermissionError('FS: Key error') from _err

    @staticmethod
    def get_sensors_temperatures():
        """Get sensors temperatures"""
        return psutil.sensors_temperatures()

    @staticmethod
    def get_sensors_fans():
        """Get sensors fans speed"""
        return psutil.sensors_fans()
