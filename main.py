import platform
import signal
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from typing import NoReturn, Final, Optional

from humanize import naturaltime

from pytmbot import logs
from pytmbot.exceptions import BotInitializationError, ShutdownError
from pytmbot.utils.system import check_python_version
from pytmbot.utils.utilities import parse_cli_args

args = parse_cli_args()

if args.health_check != "True":
    from pytmbot import pytmbot_instance

# Constants
SHUTDOWN_TIMEOUT: Final[int] = 10  # seconds
HEALTH_CHECK_INTERVAL: Final[int] = 60  # seconds
MIN_PYTHON_VERSION: Final[float] = 3.10


class HealthStatus:
    """
    Singleton class to track and manage the health status of the bot.
    """

    def __init__(self):
        self._last_health_check_result = None

    _instance: Optional["HealthStatus"] = None

    def __new__(cls) -> "HealthStatus":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def last_health_check_result(self) -> Optional[bool]:
        return self._last_health_check_result

    @last_health_check_result.setter
    def last_health_check_result(self, value: Optional[bool]) -> None:
        self._last_health_check_result = value is not None and value


class BotLauncher:
    """
    Manages the lifecycle of the PyTMBot instance including startup,
    shutdown, and health monitoring.
    """

    def __init__(self) -> None:
        """Initialize the bot launcher with signal handlers and logger."""
        self.bot: pytmbot_instance.PyTMBot | None = None
        self.logger = logs.bot_logger
        self.shutdown_requested = threading.Event()
        self.health_check_thread: threading.Thread | None = None
        self.start_time = datetime.now()

    def _signal_handler(self, signum: int, _) -> None:
        """
        Handle incoming system signals for graceful shutdown.
        """
        signal_map = {
            signal.SIGTERM: "SIGTERM",
            signal.SIGINT: "SIGINT",
            signal.SIGHUP: "SIGHUP"
        }

        try:
            sig_name = signal_map.get(signal.Signals(signum), f"Unknown signal {signum}")
        except ValueError:
            sig_name = f"Unknown signal {signum}"

        self.logger.warning(f"Received {sig_name} signal - initiating graceful shutdown...")
        self.shutdown_requested.set()

    def _health_check(self) -> None:
        """
        Periodic health check of the bot instance and system resources.
        Runs in a separate thread.
        """
        health_status = HealthStatus()

        while not self.shutdown_requested.is_set():
            try:
                if self.bot:
                    is_healthy = self.bot.is_healthy()
                    if is_healthy:
                        health_status.last_health_check_result = True
                    else:
                        health_status.last_health_check_result = False

                    if not is_healthy:
                        self.logger.warning("Bot health check failed - attempting recovery...")
                        if not self.bot.recovery():
                            self.logger.error("Recovery failed. Retrying in next check...")
                            time.sleep(HEALTH_CHECK_INTERVAL)

                uptime_display = naturaltime(self.start_time)
                self.logger.debug(
                    f"Health check passed - "
                    f"Uptime: {uptime_display}, "
                    f"Active: {bool(self.bot)}"
                )

            except Exception as e:
                self.logger.error(f"Health check error: {e}")

            time.sleep(HEALTH_CHECK_INTERVAL)

    @contextmanager
    def _managed_bot(self):
        """
        Context manager for bot lifecycle management.
        Ensures proper initialization and cleanup.
        """
        try:
            self.bot = pytmbot_instance.PyTMBot()
            yield self.bot
        finally:
            self.bot = None

    def shutdown(self) -> None:
        if not self.bot:
            return

        try:
            self.logger.info("Initiating graceful shutdown sequence...")
            self.shutdown_requested.set()

            if hasattr(self.bot, 'bot') and self.bot.bot:
                self.bot.bot.stop_polling()
                self.bot.bot.remove_webhook()

            if self.health_check_thread and self.health_check_thread.is_alive():
                self.health_check_thread.join(timeout=SHUTDOWN_TIMEOUT)

            self.logger.info("Shutdown completed successfully")

        except Exception as e:
            raise ShutdownError(f"Error during shutdown: {e}")

    def validate_environment(self) -> None:
        """
        Validate the execution environment including Python version,
        system resources, and dependencies.
        """
        try:
            if not check_python_version(MIN_PYTHON_VERSION):
                raise BotInitializationError(
                    f"Python {MIN_PYTHON_VERSION}+ required, "
                    f"but running on {platform.python_version()}"
                )

        except Exception as e:
            self.logger.exception(f"Environment validation failed: {e}")
            raise BotInitializationError(f"Environment validation failed: {e}")

    def run(self) -> NoReturn:
        """
        Main entry point for starting the bot.
        """
        try:
            # Setup signal handlers
            for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
                signal.signal(sig, self._signal_handler)

            # Validate environment
            self.validate_environment()

            # Start health check thread
            self.health_check_thread = threading.Thread(
                target=self._health_check,
                name="HealthCheckThread",
                daemon=True
            )
            self.health_check_thread.start()

            self.logger.info("Starting PyTMBot...")

            with self._managed_bot() as bot:
                # Run the bot until shutdown is requested
                bot.launch_bot()

                while not self.shutdown_requested.is_set():
                    time.sleep(1)

                # Perform cleanup
                self.shutdown()

            # Clean exit
            sys.exit(0)

        except Exception as e:
            self.logger.critical(f"Fatal error: {e}")
            sys.exit(1)


def main() -> NoReturn:
    """Main function to start the PyTMBot instance."""

    if args.health_check == "True":
        health_status = HealthStatus()
        sys.exit(0 if health_status.last_health_check_result else 1)
    else:
        launcher = BotLauncher()
        launcher.run()


if __name__ == "__main__":
    main()
