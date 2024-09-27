import threading
import time
from collections import deque
from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from pytmbot.logs import bot_logger


class MonitorPluginConfig(BaseModel):
    """
    Configuration model for the system monitoring plugin.

    This model defines the thresholds for CPU, memory, and disk usage, as well as the
    maximum number of notifications that can be sent and the interval at which system
    checks should be performed.

    Attributes:
        emoji_for_notification (str): The emoji to use for notifications.

    """

    emoji_for_notification: str = Field(default="🚢🆘🛟🚨📢\n")


class MonitoringData:
    """Singleton class for storing and managing monitoring data."""

    _instance = None
    _data_added = False

    def __new__(cls, *args, **kwargs):
        """Override __new__ to ensure only one instance is created."""
        if cls._instance is None:
            cls._instance = super(MonitoringData, cls).__new__(cls)
            bot_logger.debug("MonitoringData singleton instance created.")
        return cls._instance

    def __init__(self, retention_days: int = 7):
        """Initialize the class with a retention period."""
        # To ensure __init__ is not called multiple times in case of repeated instantiation
        if not hasattr(self, 'initialized'):  # This is to ensure it's only initialized once
            self.retention_days = retention_days
            self.data = {
                "cpu_usage": deque(),
                "memory_usage": deque(),
                "disk_usage": deque(),
                "temperatures": deque(),
            }
            self.stop_event = threading.Event()
            self.cleaning_thread = threading.Thread(target=self._clean_old_data, daemon=True)
            self.cleaning_thread.start()
            self.initialized = True  # Mark as initialized to avoid multiple initializations
            bot_logger.info(f"MonitoringData initialized with retention period of {self.retention_days} days.")

    def add_data(self, cpu: float, memory: float, disk: float, temperature: float):
        """Adds new data to the storage."""
        timestamp = datetime.now()
        self.data["cpu_usage"].append((timestamp, cpu))
        self.data["memory_usage"].append((timestamp, memory))
        self.data["disk_usage"].append((timestamp, disk))
        self.data["temperatures"].append((timestamp, temperature))
        if not self._data_added:
            bot_logger.debug(
                f"Data added to MonitoringData: CPU: {cpu}, Memory: {memory}, Disk: {disk}, Temperature: {temperature}.")
            self._data_added = True

    def _clean_old_data(self):
        """Removes data older than the retention period."""
        while not self.stop_event.is_set():
            self._remove_old_entries()
            time.sleep(3600)  # Check every hour

    def _remove_old_entries(self):
        """Removes old entries from the data."""
        cutoff_time = datetime.now() - timedelta(days=self.retention_days)
        for key in self.data.keys():
            old_count = len(self.data[key])
            while self.data[key] and self.data[key][0][0] < cutoff_time:
                self.data[key].popleft()
            if old_count != len(self.data[key]):
                bot_logger.debug(f"Removed old entries from {key}, new count: {len(self.data[key])}.")

    def stop_cleaning(self):
        """Stops the background cleaning thread."""
        self.stop_event.set()
        self.cleaning_thread.join()
        bot_logger.debug("Stopped the cleaning thread for MonitoringData.")

    def get_data(self):
        """Returns the stored data."""
        bot_logger.debug("Data retrieved from MonitoringData.")
        return {key: list(value) for key, value in self.data.items()}
