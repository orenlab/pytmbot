#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
import psutil
import app.utilities.utilities as utilities


class PsutilAdapter:
    """Class to adapt psutil to pyTMBot"""

    def __init__(self):
        self.psutil = psutil
        self.fs_current = []
        self.sensors_current = []
        self.sensors_value = []
        self.format_bytes = utilities.format_bytes

    @staticmethod
    def get_load_average():
        """Get the load average"""
        return psutil.getloadavg()

    @staticmethod
    def get_cpu_count():
        """Get cpu count"""
        return psutil.cpu_count()

    @staticmethod
    def get_memory():
        """Get current memory usage"""
        data = psutil.virtual_memory()
        return data

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
                    key: value,
                })
            i = 0
            for value in self.sensors_current:
                self.sensors_value[i] = {
                    'device_name': self.sensors_current[i],
                    'current': value[1]['current']
                }
            return self.sensors_value
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


if __name__ == '__main__':
    psutil_adapter = PsutilAdapter()
    print(psutil_adapter.get_load_average())
