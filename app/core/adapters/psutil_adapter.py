#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
import psutil


class PsutilAdapter:
    """Class to psutil communication with Telegram bot"""

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

    @staticmethod
    def get_disk_partition():
        """Get disk partition list"""
        return psutil.disk_partitions()

    @staticmethod
    def get_disk_usage(partition_name: str):
        """Get partition usage"""
        return psutil.disk_usage(partition_name)

    @staticmethod
    def get_sensors_temperatures():
        """Get sensors temperatures"""
        return psutil.sensors_temperatures()

    @staticmethod
    def get_sensors_fans():
        """Get sensors fans speed"""
        return psutil.sensors_fans()
