import importlib.util
import threading
import time

from telebot import TeleBot

from pytmbot.plugins.plugins_core import PluginCore

# Check if the psutil module is installed
if importlib.util.find_spec("psutil") is None:
    raise ModuleNotFoundError("psutil library is not installed. Please install it.")

import psutil


class SystemMonitorPlugin(PluginCore):
    """
    A plugin for monitoring system resources such as CPU, memory, and disk usage.
    Sends notifications to a Telegram bot if any of the monitored resources exceed specified thresholds.

    Attributes:
        config (object): Configuration object containing thresholds and other settings.
        bot (TeleBot): Instance of the Telegram bot.
        monitoring (bool): Flag to indicate whether monitoring is active.
        notification_count (int): Counter for the number of notifications sent.
        max_notifications (int): Maximum number of notifications to be sent.
        monitoring_thread (threading.Thread): The thread responsible for monitoring the system.
        retry_attempts (int): Number of attempts to retry starting monitoring in case of failure.
        retry_interval (int): Interval (in seconds) between retry attempts.
    """

    def __init__(self, config, bot: TeleBot):
        """
        Initializes the SystemMonitorPlugin with the given configuration and bot instance.

        Args:
            config: Configuration object containing thresholds and other settings.
            bot (TeleBot): Instance of the Telegram bot.
        """
        super().__init__()
        self.bot = bot
        self.config = config
        self.monitoring = False
        self.notification_count = 0
        self.max_notifications = self.config.max_notifications
        self.monitoring_thread = None
        self.retry_attempts = 3
        self.retry_interval = 5

    def start_monitoring(self):
        """
        Starts the system monitoring process in a separate thread.
        If the monitoring fails to start, it will retry up to `retry_attempts` times.
        """
        if not self.monitoring:
            self.bot_logger.info("Attempting to start system monitoring.")
            for attempt in range(self.retry_attempts):
                try:
                    self.monitoring = True
                    self.monitoring_thread = threading.Thread(
                        target=self._monitor_system, daemon=True
                    )
                    self.monitoring_thread.start()
                    self.bot_logger.info("System monitoring started successfully.")
                    return
                except Exception as e:
                    self.bot_logger.error(f"Failed to start monitoring on attempt {attempt + 1}: {e}")
                    self.monitoring = False
                    time.sleep(self.retry_interval)

            self.bot_logger.error("Failed to start system monitoring after multiple attempts. Manual restart required.")
        else:
            self.bot_logger.warning("Monitoring is already running.")

    def stop_monitoring(self):
        """
        Stops the system monitoring process and waits for the monitoring thread to terminate.
        """
        if self.monitoring:
            self.monitoring = False
            if self.monitoring_thread is not None:
                self.monitoring_thread.join()
            self.bot_logger.info("System monitoring stopped.")
        else:
            self.bot_logger.warning("Monitoring is not running.")

    def _monitor_system(self):
        """
        Continuously monitors the system resources (CPU, memory, and disk usage)
        and sends notifications if any resource exceeds the configured thresholds.
        """
        try:
            while self.monitoring:
                self._check_cpu_usage()
                self._check_memory_usage()
                self._check_disk_usage()
                time.sleep(self.config.check_interval)
        except Exception as e:
            self.bot_logger.error(f"Unexpected error during system monitoring: {e}")
            self.monitoring = False

    def _check_cpu_usage(self):
        """
        Checks the current CPU usage and sends a notification if it exceeds the configured threshold.
        """
        try:
            cpu_usage = psutil.cpu_percent(interval=1)
            if cpu_usage > self.config.cpu_threshold:
                self._send_notification(f"{self.config.emoji_for_notification}CPU usage is high: {cpu_usage}%")
        except psutil.Error as e:
            self.bot_logger.error(f"Error checking CPU usage: {e}")

    def _check_memory_usage(self):
        """
        Checks the current memory usage and sends a notification if it exceeds the configured threshold.
        """
        try:
            memory = psutil.virtual_memory()
            if memory.percent > self.config.memory_threshold:
                self._send_notification(f"{self.config.emoji_for_notification}Memory usage is high: {memory.percent}%")
        except psutil.Error as e:
            self.bot_logger.error(f"Error checking memory usage: {e}")

    def _check_disk_usage(self):
        """
        Checks the current disk usage for all partitions and sends a notification
        if any partition's usage exceeds the configured threshold.
        """
        try:
            for partition in psutil.disk_partitions():
                usage = psutil.disk_usage(partition.mountpoint)
                if usage.percent > self.config.disk_threshold:
                    self._send_notification(
                        f"{self.config.emoji_for_notification}Disk usage is high on {partition.device}: {usage.percent}%")
        except psutil.Error as e:
            self.bot_logger.error(f"Error checking disk usage: {e}")
        except Exception as e:
            self.bot_logger.error(f"Unexpected error while checking disk usage: {e}")

    def _send_notification(self, message):
        """
        Sends a notification message to the Telegram bot chat.
        If the maximum number of notifications has been reached, no further notifications will be sent.

        Args:
            message (str): The notification message to be sent.
        """
        if self.notification_count < self.max_notifications:
            try:
                self.notification_count += 1
                sanitize_message = message.replace(self.config.emoji_for_notification, '')
                self.bot_logger.info(f"Sending notification: {sanitize_message}")
                self.bot.send_message(self.settings.chat_id.global_chat_id[0], message)

                # Start a timer to reset the notification count after 5 minutes (300 seconds)
                threading.Timer(300, self._reset_notification_count).start()

            except Exception as e:
                self.bot_logger.error(f"Failed to send notification: {e}")
        else:
            self.bot_logger.warning("Max notifications reached; no more notifications will be sent.")

    def _reset_notification_count(self):
        """
        Resets the notification count to 0 after a specified delay.
        """
        self.notification_count = 0
        self.bot_logger.info("Notification count has been reset.")


__all__ = ["SystemMonitorPlugin"]
