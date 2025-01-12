import os
import platform
import signal
import sys
import threading
import time
import traceback
from contextlib import contextmanager
from datetime import datetime
from typing import NoReturn, Final, Optional

from humanize import naturaltime

from pytmbot import logs
from pytmbot.exceptions import (
    InitializationError,
    ShutdownError,
    ErrorContext
)
from pytmbot.utils import parse_cli_args

args = parse_cli_args()

if not args.health_check:
    from pytmbot import pytmbot_instance


class HealthStatus:
    """Singleton class to track and manage the health status of the bot."""
    __slots__ = ('_last_health_check_result', '_last_check_time')
    _instance: Optional["HealthStatus"] = None

    def __init__(self):
        self._last_health_check_result = None
        self._last_check_time = None

    def __new__(cls) -> "HealthStatus":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._last_health_check_result = None
            cls._instance._last_check_time = None
        return cls._instance

    @property
    def last_health_check_result(self) -> Optional[bool]:
        if (self._last_check_time is None or
                time.time() - self._last_check_time > 2 * BotLauncher.HEALTH_CHECK_INTERVAL):
            return None
        return self._last_health_check_result

    @last_health_check_result.setter
    def last_health_check_result(self, value: Optional[bool]) -> None:
        self._last_health_check_result = value is not None and value
        self._last_check_time = time.time()


class BotLauncher(logs.BaseComponent):
    __slots__ = ('bot', 'shutdown_requested', 'health_check_thread', 'start_time')

    SHUTDOWN_TIMEOUT: Final[int] = 10
    HEALTH_CHECK_INTERVAL: Final[int] = 60
    MIN_PYTHON_VERSION: Final[float] = 3.10

    def __init__(self) -> None:
        super().__init__("bot_launcher")
        self.bot = None
        self.shutdown_requested = threading.Event()
        self.health_check_thread = None
        self.start_time = datetime.now()

    def _signal_handler(self, signum: int, _) -> None:
        try:
            sig_name = signal.Signals(signum).name
        except ValueError:
            sig_name = f"Unknown signal {signum}"

        with self.log_context(signal=sig_name) as log:
            log.warning("Received signal - initiating graceful shutdown")
        self.shutdown_requested.set()

    def _health_check(self) -> None:
        health_status = HealthStatus()

        while not self.shutdown_requested.is_set():
            try:
                if self.bot:
                    is_healthy = self.bot.is_healthy()
                    health_status.last_health_check_result = is_healthy

                    if not is_healthy:
                        with self.log_context(recovery_attempt=True) as log:
                            log.warning("Bot health check failed - attempting recovery")
                            if not self.bot.recovery():
                                log.error("Recovery failed. Retrying in next check")
                                time.sleep(self.HEALTH_CHECK_INTERVAL)

                    uptime_display = naturaltime(self.start_time)
                    with self.log_context(
                            uptime=uptime_display,
                            active=bool(self.bot)
                    ) as log:
                        log.debug("Health check passed")

            except Exception as e:
                with self.log_context(error=str(e)):
                    log.error("Health check error")

            time.sleep(self.HEALTH_CHECK_INTERVAL)

    @contextmanager
    def _managed_bot(self):
        try:
            self.bot = pytmbot_instance.PyTMBot()
            yield self.bot
        finally:
            self.bot = None

    def shutdown(self) -> None:
        if not self.bot:
            return

        try:
            with self.log_context() as log:
                log.info("Initiating graceful shutdown sequence")
                self.shutdown_requested.set()

                if hasattr(self.bot, 'bot') and self.bot.bot:
                    self.bot.bot.stop_polling()
                    self.bot.bot.remove_webhook()

                if self.health_check_thread and self.health_check_thread.is_alive():
                    self.health_check_thread.join(timeout=self.SHUTDOWN_TIMEOUT)

                    log.info("Shutdown completed successfully")

        except Exception as e:
            raise ShutdownError(ErrorContext(
                message=f"Error during shutdown: {str(e)}",
                metadata={"exception": str(e)}
            ))

    def validate_environment(self) -> None:
        try:
            from pytmbot.utils.system import check_python_version
            if not check_python_version(self.MIN_PYTHON_VERSION):
                raise InitializationError(ErrorContext(
                    message=f"Python {self.MIN_PYTHON_VERSION}+ required, but running on {platform.python_version()}",
                    error_code="INIT_001",
                    metadata={"current_version": platform.python_version()}
                ))

        except Exception as e:
            raise InitializationError(ErrorContext(
                message=f"Environment validation failed: {str(e)}",
                error_code="INIT_002",
                metadata={"original_error": str(e)}
            ))

    def run(self) -> NoReturn:
        try:
            for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
                signal.signal(sig, self._signal_handler)

            self.validate_environment()

            self.health_check_thread = threading.Thread(
                target=self._health_check,
                name="HealthCheckThread",
                daemon=True
            )
            self.health_check_thread.start()

            with self.log_context() as log:
                log.info("Starting PyTMBot")

            with self._managed_bot() as bot:
                bot.launch_bot()
                while not self.shutdown_requested.is_set():
                    time.sleep(1)
                self.shutdown()

            sys.exit(0)

        except Exception as e:
            ctx = {
                'exception_type': type(e).__name__,
                'exception_value': str(e),
                'traceback': traceback.format_exc(),
                'shutdown_requested': self.shutdown_requested.is_set(),
                'last_health_check_result': HealthStatus().last_health_check_result,
                'uptime': naturaltime(self.start_time),
                'active': bool(self.bot),
                'pid': os.getpid(),
                'python_version': platform.python_version(),
                'system': platform.system(),
                'architecture': platform.machine(),
                'platform': platform.platform()
            }
            with self.log_context(**ctx) as log:
                log.critical("Fatal error. Exiting...")
            sys.exit(1)


def main() -> NoReturn:
    if args.health_check:
        sys.exit(0 if HealthStatus().last_health_check_result is True else 1)
    else:
        launcher = BotLauncher()
        launcher.run()


if __name__ == "__main__":
    main()
