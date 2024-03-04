#!/usr/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
import psutil


class PsutilAdapter:
    @staticmethod
    def get_load_average():
        return psutil.getloadavg()

    @staticmethod
    def get_memory():
        return psutil.virtual_memory()

    @staticmethod
    def get_swap_memory():
        return psutil.swap_memory()

    @staticmethod
    def get_disk_partition():
        return psutil.disk_partitions()

    @staticmethod
    def get_disk_usage(partition_name: str):
        return psutil.disk_usage(partition_name)

    @staticmethod
    def get_sensors_temperatures():
        return psutil.sensors_temperatures()

    @staticmethod
    def get_sensors_fans():
        return psutil.sensors_fans()


psutil_adapter = PsutilAdapter()

if __name__ == '__main__':
    print(psutil_adapter.get_sensors_temperatures())
