#!/venv/bin/python3
"""
(c) Copyright 2024, Denis Rozhnovskiy <pytelemonbot@mail.ru>
PyTMBot - A simple Telegram bot designed to gather basic information about
the status of your local servers
"""
from datetime import datetime
from typing import Tuple

import psutil
from humanize import naturalsize

from app.core.logs import bot_logger


class PsutilAdapter:
    """
    Class to adapt psutil to pyTMBot.

    Attributes:
        psutil (module): The psutil module.
        fs_current (None): The current file system statistics.
        sensors_current (list): The current sensor statistics.
        memory_stat (None): The current memory statistics.
        fs_stats (None): The file system statistics.
        fs_usage (None): The file system usage statistics.
        memory_current (None): The current memory usage.
        sensors_stat (None): The sensor statistics.
        sw_current (None): The current software information.
        process_count (dict): The count of running, sleeping, and idle processes.
        sleeping (int): The count of sleeping processes.
        running (int): The count of running processes.
        idle (int): The count of idle processes.
        net_io_stat (None): The network I/O statistics.
    """

    def __init__(self):
        """
        Initialize the PsutilAdapter class.

        This method initializes all the attributes of the class.
        """
        self.psutil = psutil  # Import the psutil module
        self.fs_current = None  # Initialize the current file system statistics
        self.sensors_current = []  # Initialize the current sensor statistics
        self.memory_stat = None  # Initialize the current memory statistics
        self.fs_stats = None  # Initialize the file system statistics
        self.fs_usage = None  # Initialize the file system usage statistics
        self.memory_current = None  # Initialize the current memory usage
        self.sensors_stat = None  # Initialize the sensor statistics
        self.sw_current = None  # Initialize the current software information
        self.process_count = {}  # Initialize the count of running, sleeping, and idle processes
        self.sleeping = 0  # Initialize the count of sleeping processes
        self.running = 0  # Initialize the count of running processes
        self.idle = 0  # Initialize the count of idle processes
        self.net_io_stat = None  # Initialize the network I/O statistics

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

    @staticmethod
    def get_cpu_count() -> int:
        """
        Get the number of CPU cores available on the system.

        Returns:
            The number of CPU cores as an integer.
        """
        # Log a debug message indicating that the CPU count is being retrieved
        bot_logger.debug("Retrieving CPU count")

        # Use the `psutil` library to get the number of CPU cores
        cpu_count = psutil.cpu_count()

        # Log a debug message indicating that the CPU count has been received
        bot_logger.debug("CPU count received")

        return cpu_count

    def get_memory(self):
        """
        Get current memory usage.

        This function retrieves the current memory usage statistics and returns them as a dictionary.

        Returns:
            dict: A dictionary containing the following memory usage statistics:
                - total: The total amount of memory in bytes.
                - available: The amount of available memory in bytes.
                - percent: The percentage of memory used.
                - used: The amount of memory used in bytes.
                - free: The amount of free memory in bytes.
                - active: The amount of active memory in bytes.
                - inactive: The amount of inactive memory in bytes.
                - cached: The amount of cached memory in bytes.
                - shared: The amount of shared memory in bytes.

        Raises:
            PermissionError: If the user does not have permission to access memory statistics.
            ValueError: If there is an error retrieving memory statistics.
        """
        try:
            # Unset the memory_current attribute
            self.memory_current = ''

            # Retrieve memory statistics using the psutil library
            self.memory_stat = self.psutil.virtual_memory()

            # Create a dictionary with memory usage statistics
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

            # Log a debug message indicating that memory statistics have been received
            bot_logger.debug(f"Memory stats is received: {self.memory_current}")

            # Return the memory usage statistics
            return self.memory_current

        except (PermissionError, ValueError) as e:
            # Log an error message if there is an error retrieving memory statistics
            bot_logger.error(f"Failed at @{__name__}: {e}")

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
            self.fs_current = []  # Unset attribute
            self.fs_stats = psutil.disk_partitions(all=False)
            bot_logger.debug(f"Partitions stats is received: {self.fs_stats}")

            for fs in self.fs_stats:
                try:
                    self.fs_usage = self.psutil.disk_usage(fs.mountpoint)
                except OSError:
                    continue

                # Create a dictionary with the usage statistics for the partition
                fs_stat = {
                    'device_name': fs.device,
                    'fs_type': fs.fstype,
                    'mnt_point': fs.mountpoint.replace(u'\u00A0', ' '),
                    'size': naturalsize(self.fs_usage.total, binary=True),
                    'used': naturalsize(self.fs_usage.used, binary=True),
                    'free': naturalsize(self.fs_usage.free, binary=True),
                    'percent': self.fs_usage.percent
                }

                self.fs_current.append(fs_stat)

            bot_logger.debug(f"File system stats is received: {self.fs_current}")
            return self.fs_current

        except (PermissionError, KeyError) as e:
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
            # Unset the sw_current attribute
            self.sw_current = []

            # Retrieve swap memory statistics using the psutil library
            swap = psutil.swap_memory()

            # Create a dictionary with swap memory usage statistics
            self.sw_current = {
                'total': naturalsize(swap.total, binary=True),
                'used': naturalsize(swap.used, binary=True),
                'free': naturalsize(swap.free, binary=True),
                'percent': swap.percent,
            }

            # Log a debug message indicating that swap memory statistics have been received
            bot_logger.debug(f"Swap memory stats is received: {self.sw_current}")

            # Return the swap memory usage statistics
            return self.sw_current

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
            # Unset the sensors_current attribute
            self.sensors_current = []

            # Retrieve the current temperature statistics from the system's sensors
            self.sensors_stat = self.psutil.sensors_temperatures()

            # Log a debug message indicating that sensors statistics have been received
            bot_logger.debug("Sensors stats is received")

            # If no sensors statistics are available, log an error message
            if not self.sensors_stat:
                bot_logger.debug("Error receiving data from temperature sensors")

            # Create a list of dictionaries, where each dictionary contains the sensor name
            # and its current temperature
            # Iterate over the sensors and their temperature statistics
            for sensor_name, temperature_stats in self.sensors_stat.items():
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
    def get_sensors_fans():
        """
        Get the speed of all fans in the system's sensors.

        Returns:
            A dictionary containing the speed of each fan in RPM.
        """
        # Use the psutil library to retrieve the speed of all fans in the system's sensors
        fans_speeds = psutil.sensors_fans()

        # Return the dictionary containing the speed of each fan
        return fans_speeds

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
        process_counts = {
            'running': 0,
            'sleeping': 0,
            'idle': 0,
            'total': 0
        }

        try:
            for proc in self.psutil.process_iter():
                process_status = proc.status()
                process_counts[process_status] += 1

            # Log the completion of process iteration
            bot_logger.debug("Proc iterate stats done")

            process_counts['total'] = sum(process_counts.values())

            return process_counts

        except AttributeError as e:
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
            self.net_io_stat = self.psutil.net_io_counters()

            # Log the receipt of network I/O statistics
            bot_logger.debug("Network IO stat recv")

            # Append the network I/O statistics to the list
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

            # Log the completion of appending the network I/O statistics
            bot_logger.debug(f"Network IO stat append done: {net_io_stat_current}")

            return net_io_stat_current

        except AttributeError as e:
            # Log the error if an AttributeError occurs
            bot_logger.error(f"Failed at @{__name__}: {e}")
