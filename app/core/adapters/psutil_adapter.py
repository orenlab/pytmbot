#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
import re
from datetime import datetime
from typing import Tuple

import psutil
from humanize import naturalsize

from app.core.logs import bot_logger


class PsutilAdapter:
    """
    A class that wraps the psutil library for easier usage.

    Methods:
        get_load_average()
        get_disk_usage()
        get_memory()
        get_swap_memory()
        get_net_io_counters()

    Attributes:
        psutil (psutil): An instance of the psutil library.
        sensors_current (list): An empty list to store the current sensor data.
    """

    def __init__(self):
        """
        Initialize the PsutilAdapter class.

        This method initializes the PsutilAdapter class by creating an instance of the psutil library and an empty list
        to store the current sensor data.

        Returns:
            None
        """
        # Create an instance of the psutil library
        self.psutil = psutil

        # Create an empty list to store the current sensor data
        self.sensors_current = []

    @staticmethod
    def get_load_average() -> Tuple[float, float, float]:
        """
        Get the load average.

        This method retrieves the load average from the system using the `psutil` library.
        The load average is a measure of the average number of processes in the run queue
        or waiting for CPU time over a given period of time.

        Returns:
            A tuple containing the load average for the last 1 minute, 5 minutes, and 15 minutes.
        """
        # Log a debug message indicating that the load average stats are received
        bot_logger.debug("Load Average stats is received")

        # Retrieve the load average from the system using the `psutil` library
        load_average = psutil.getloadavg()

        return load_average

    def get_memory(self):
        """
        Retrieve current memory usage statistics.

        Returns:
            dict: Dictionary with memory usage statistics:
                - total: Total memory in bytes.
                - available: Available memory in bytes.
                - percent: Percentage of memory used.
                - used: Memory used in bytes.
                - free: Free memory in bytes.
                - active: Active memory in bytes.
                - inactive: Inactive memory in bytes.
                - cached: Cached memory in bytes.
                - shared: Shared memory in bytes.

        Raises:
            PermissionError: If permission to access memory statistics is denied.
            ValueError: If there is an error retrieving memory statistics.
        """
        try:
            # Print a debug message before retrieving memory stats
            bot_logger.debug("Retrieving memory statistics...")

            # Retrieve memory statistics using the psutil library
            memory_stats = self.psutil.virtual_memory()

            # Generate the memory usage dictionary
            memory_current = {
                stat: naturalsize(getattr(memory_stats, stat), binary=True)
                for stat in ['total', 'available', 'percent', 'used', 'free', 'active', 'inactive', 'cached', 'shared']
            }

            # Print a debug message after retrieving memory stats
            bot_logger.debug(f"Memory statistics retrieved successfully: {memory_current}")

            return memory_current

        except (PermissionError, ValueError) as e:
            # Log an error message if there is an exception
            bot_logger.error(f"Failed to retrieve memory statistics: {e}")

    def get_disk_usage(self):
        """
        Get partition usage statistics.

        Returns:
            A list of dictionaries containing the usage statistics for each partition.
            Each dictionary contains the following keys:
                - device_name (str): The device name.
                - fs_type (str): The file system type.
                - mnt_point (str): The mount point.
                - size (str): The total size of the partition in a human-readable format.
                - used (str): The used space of the partition in a human-readable format.
                - free (str): The free space of the partition in a human-readable format.
                - percent (float): The usage percentage of the partition.

        Raises:
            PermissionError: If the user does not have permission to access the disk partitions.
            KeyError: If there is an error retrieving the disk partitions.
        """
        try:
            # Retrieve disk partitions
            fs_stats = psutil.disk_partitions(all=False)
            bot_logger.debug(f"Partitions stats is received: {fs_stats}")

            # Generate a list of dictionaries containing the usage statistics for each partition
            fs_current = [
                {
                    'device_name': fs.device,  # Device name
                    'fs_type': fs.fstype,  # File system type
                    'mnt_point': re.sub(r'\u00A0', ' ', fs.mountpoint),  # Mount point
                    'size': naturalsize(self.psutil.disk_usage(fs.mountpoint).total, binary=True),  # Total size
                    'used': naturalsize(self.psutil.disk_usage(fs.mountpoint).used, binary=True),  # Used space
                    'free': naturalsize(self.psutil.disk_usage(fs.mountpoint).free, binary=True),  # Free space
                    'percent': self.psutil.disk_usage(fs.mountpoint).percent  # Usage percentage
                }
                for fs in fs_stats
            ]

            bot_logger.debug(f"File system stats is received: {fs_current}")
            return fs_current

        except (PermissionError, KeyError) as e:
            # Log an error message if there is an exception
            bot_logger.error(f"Failed at @{__name__}: {e}")

    def get_swap_memory(self):
        """
        Get swap memory usage.

        This function retrieves the current swap memory usage statistics and returns them as a dictionary.

        Returns:
            dict: A dictionary containing the following swap memory usage statistics:
                - total: The total amount of swap memory in bytes.
                - used: The amount of used swap memory in bytes.
                - free: The amount of free swap memory in bytes.
                - percent: The percentage of swap memory used.

        Raises:
            PermissionError: If the user does not have permission to access swap memory statistics.
        """
        try:
            # Print a debug message before retrieving swap memory stats
            bot_logger.debug("Retrieving swap memory statistics...")

            # Retrieve swap memory statistics using the psutil library
            swap = self.psutil.swap_memory()

            # Create a dictionary with swap memory usage statistics
            sw_current = {
                'total': naturalsize(swap.total, binary=True),
                'used': naturalsize(swap.used, binary=True),
                'free': naturalsize(swap.free, binary=True),
                'percent': swap.percent,
            }

            # Log a debug message indicating that swap memory statistics have been received
            bot_logger.debug(f"Swap memory stats is received: {sw_current}")

            # Return the swap memory usage statistics
            return sw_current

        except PermissionError as e:
            # Log an error message if there is an error retrieving swap memory statistics
            bot_logger.error(f"Failed at @{__name__}: {e}")

    def get_sensors_temperatures(self):
        """
        Get sensors temperatures.

        This function retrieves the current temperature statistics from the system's sensors.
        It uses the psutil library to gather this information. The function returns a list
        of dictionaries, where each dictionary represents a sensor and its current temperature.

        Returns:
            list: A list of dictionaries, where each dictionary contains the sensor name
            and its current temperature.
        """
        try:
            # Print a debug message before retrieving sensors statistics
            bot_logger.debug("Retrieving sensors statistics...")

            # Retrieve the current temperature statistics from the system's sensors
            sensors_stat = self.psutil.sensors_temperatures()

            # If no sensors statistics are available, log an error message
            if not sensors_stat:
                bot_logger.debug("Error receiving data from temperature sensors")

            # Create a list of dictionaries, where each dictionary contains the sensor name
            # and its current temperature
            # Iterate over the sensors and their temperature statistics
            for sensor_name, temperature_stats in sensors_stat.items():
                sensor_data = {
                    'sensor_name': sensor_name,
                    'sensor_value': temperature_stats[0][1],
                }

                # Append the sensor data to the sensors_current list
                self.sensors_current.append(sensor_data)

            # Log a debug message indicating the sensors statistics have been appended
            bot_logger.debug(f"Sensors stats append: {self.sensors_current}")

            # Return the sensors statistics
            return self.sensors_current

        except (AttributeError, KeyError, ValueError) as e:
            # Log an error message if there is an error retrieving sensors statistics
            bot_logger.error(f"Failed at @{__name__}: {e}")

    @staticmethod
    def get_uptime() -> str:
        """
        Get the system uptime.

        Returns:
            str: The uptime in the format 'X days, Y hours, Z minutes, A seconds'.
        """
        # Calculate the raw uptime by subtracting the system boot time from the current time
        uptime_raw = datetime.now() - datetime.fromtimestamp(psutil.boot_time())

        # Convert the uptime to a string and remove the milliseconds
        uptime = str(uptime_raw).split('.')[0]

        # Log the received uptime
        bot_logger.debug(f"Uptime stats is received: {uptime}")

        # Return the uptime as a string
        return uptime

    def get_process_counts(self):
        """
        Get the counts of running, sleeping, and idle processes.

        Returns:
            dict: A dictionary containing the counts of running, sleeping, idle, and total processes.
        """
        try:
            # Get the counts of running, sleeping, and idle processes
            process_counts = {
                status: sum(1 for proc in self.psutil.process_iter() if proc.status() == status)
                for status in ['running', 'sleeping', 'idle']
            }

            # Calculate the total number of processes
            process_counts['total'] = sum(process_counts.values())

            # Log the process counts for debugging
            bot_logger.debug("Process Counts:", process_counts)

            return process_counts
        except AttributeError as e:
            # Log an error if an attribute error occurs
            bot_logger.error(f"Failed at @{__name__}: {e}")

    def get_net_io_counters(self):
        """
        Retrieves network I/O statistics using the psutil library.

        Returns:
            list: A list containing the network I/O statistics.
        """
        try:
            # Initialize an empty list to store the network I/O statistics
            net_io_stat_current = []

            # Retrieve the network I/O statistics using the psutil library
            net_io_stat = self.psutil.net_io_counters()

            # Log the receipt of network I/O statistics
            bot_logger.debug("Network IO stat recv")

            # Append the network I/O statistics to the list
            net_io_stat_current.append({
                'bytes_sent': naturalsize(net_io_stat.bytes_recv, binary=True),
                'bytes_recv': naturalsize(net_io_stat.packets_recv, binary=True),
                'packets_sent': net_io_stat.packets_sent,
                'packets_recv': net_io_stat.packets_recv,
                'err_in': net_io_stat.errin,
                'err_out': net_io_stat.errout,
                'drop_in': net_io_stat.dropin,
                'drop_out': net_io_stat.dropout
            })

            # Log the completion of appending the network I/O statistics
            bot_logger.debug(f"Network IO stat append done: {net_io_stat_current}")

            return net_io_stat_current

        except AttributeError as e:
            # Log the error if an AttributeError occurs
            bot_logger.error(f"Failed at @{__name__}: {e}")
