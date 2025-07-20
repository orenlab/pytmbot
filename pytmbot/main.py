#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import atexit
import os
import platform
import signal
import sys
import threading
import time
import traceback
from collections.abc import Generator
from contextlib import contextmanager
from datetime import datetime
from typing import NoReturn, Final, Any, Self

from humanize import naturaltime

from pytmbot import logs
from pytmbot.adapters.psutil.adapter import PsutilAdapter
from pytmbot.exceptions import InitializationError, ShutdownError, ErrorContext
from pytmbot.middleware.session_manager import SessionManager
from pytmbot.utils import parse_cli_args

args = parse_cli_args()

if not args.health_check:
    from pytmbot import pytmbot_instance


class HealthStatus:
    """Singleton class to track and manage the health status of the bot."""

    _instance: "HealthStatus | None" = None
    _lock = threading.RLock()

    def __init__(self) -> None:
        self._last_health_check_result: bool | None = None
        self._last_check_time: float | None = None
        self._instance_lock = threading.RLock()

    def __new__(cls) -> Self:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def last_health_check_result(self) -> bool | None:
        with self._instance_lock:
            if (
                self._last_check_time is None
                or time.time() - self._last_check_time
                > 2 * BotLauncher.HEALTH_CHECK_INTERVAL
            ):
                return None
            return self._last_health_check_result

    @last_health_check_result.setter
    def last_health_check_result(self, value: bool | None) -> None:
        with self._instance_lock:
            self._last_health_check_result = value is not None and value
            self._last_check_time = time.time()

    def update_health(self, is_healthy: bool) -> None:
        """Update health status with current timestamp."""
        self.last_health_check_result = is_healthy


class BotLauncher(logs.BaseComponent):
    """Main bot launcher with lifecycle management."""

    SHUTDOWN_TIMEOUT: Final[int] = 10
    HEALTH_CHECK_INTERVAL: Final[int] = 60
    MIN_PYTHON_VERSION: Final[tuple[int, int]] = (3, 10)
    MAIN_LOOP_TIMEOUT: Final[float] = 0.5
    STARTUP_GRACE_PERIOD: Final[int] = 30

    def __init__(self) -> None:
        super().__init__("bot_launcher")
        self.bot = None
        self.shutdown_requested = threading.Event()
        self.health_check_thread: threading.Thread | None = None
        self.start_time = datetime.now()
        self._shutdown_lock = threading.RLock()
        self._cleanup_registered = False
        self._sigint_count = 0
        self._sigint_lock = threading.Lock()
        self._psutil_adapter = PsutilAdapter()
        self._session_manager = SessionManager()
        self._bot_fully_started = False

    def _register_cleanup(self) -> None:
        """Register cleanup handler to ensure proper shutdown on exit."""
        if not self._cleanup_registered:
            atexit.register(self._emergency_cleanup)
            self._cleanup_registered = True

    def _shutdown_bot_silently(self, *, silent: bool) -> None:
        """Stop polling and remove webhook with optional error handling."""
        if not self.bot or not hasattr(self.bot, "bot") or not self.bot.bot:
            return

        try:
            self.bot.bot.stop_polling()
            self.bot.bot.remove_webhook()
            self._session_manager.shutdown()
        except Exception as e:
            if not silent:
                with self.log_context(error=str(e)) as log:
                    log.warning("Bot shutdown encountered issues")

    def _emergency_cleanup(self) -> None:
        """Emergency cleanup for atexit - minimal operations only."""
        self._shutdown_bot_silently(silent=True)

    def _stop_bot_operations(self) -> None:
        """Stop bot operations safely with error handling."""
        self._shutdown_bot_silently(silent=False)

    def _handle_sigint(self, sig_name: str) -> None:
        """Handle SIGINT with graceful -> forced shutdown logic."""
        with self._sigint_lock:
            self._sigint_count += 1

            if self._sigint_count == 1:
                with self.log_context(signal=sig_name) as log:
                    log.info("Graceful shutdown initiated (Ctrl+C again to force)")
                self.shutdown_requested.set()
            elif self._sigint_count >= 2:
                with self.log_context(signal=sig_name) as log:
                    log.warning("Forced shutdown initiated")
                self._emergency_cleanup()
                signal.signal(signal.SIGINT, signal.SIG_DFL)
                os.kill(os.getpid(), signal.SIGINT)

    def _signal_handler(self, signum: int, frame) -> None:
        """Signal handler for graceful shutdown."""
        try:
            sig_name = signal.Signals(signum).name
        except ValueError:
            sig_name = f"signal_{signum}"

        if signum == signal.SIGINT:
            self._handle_sigint(sig_name)
        else:
            with self.log_context(signal=sig_name) as log:
                log.info("Shutdown initiated by signal")
            self.shutdown_requested.set()
            self._stop_bot_operations()

    @contextmanager
    def _managed_bot(self) -> Generator[Any, None, None]:
        """Context manager for bot lifecycle."""
        try:
            self.bot = pytmbot_instance.PyTMBot()
            yield self.bot
        except Exception as e:
            with self.log_context(error=str(e)) as log:
                log.error("Bot creation failed")
            raise
        finally:
            self._cleanup_bot()

    def _perform_health_check(self) -> bool:
        """Perform a single health check with error handling."""
        if not self.bot:
            return False

        try:
            is_healthy = self.bot.is_healthy()
            if not is_healthy:
                with self.log_context() as log:
                    log.warning("Bot health check failed, attempting recovery")
                if not self.bot.recovery():
                    with self.log_context() as log:
                        log.error("Bot recovery failed")
            return is_healthy
        except Exception as e:
            with self.log_context(error=str(e)) as log:
                log.error("Health check failed with exception")
            return False

    def _health_check_loop(self) -> None:
        """Health check loop with proper error handling."""
        health_status = HealthStatus()

        while not self.shutdown_requested.is_set():
            is_healthy = self._perform_health_check()
            health_status.update_health(is_healthy)

            self._log_health_status()

            # Wait with early exit on shutdown
            for _ in range(self.HEALTH_CHECK_INTERVAL):
                if self.shutdown_requested.wait(timeout=1):
                    return

    @staticmethod
    def _is_monitor_plugin_loaded() -> bool:
        from pytmbot.plugins.plugin_manager import PluginManager

        return PluginManager.is_plugin_loaded("monitor")

    def _is_within_startup_grace_period(self) -> bool:
        """Check if we're still within the startup grace period."""
        uptime_seconds = (datetime.now() - self.start_time).total_seconds()
        return uptime_seconds < self.STARTUP_GRACE_PERIOD

    def _log_health_status(self) -> None:
        """Log current health status with comprehensive process statistics."""
        uptime_display = naturaltime(self.start_time)

        rate_limit_stats = None
        if self.bot and hasattr(self.bot, "get_rate_limit_stats"):
            rate_limit_stats = self.bot.get_rate_limit_stats()

        log_context = {
            "uptime": uptime_display,
            "active": bool(self.bot),
            "admin_sessions": self._session_manager.get_session_stats(),
            "rate_limit_middleware_metrics": rate_limit_stats,
        }

        if not self._is_monitor_plugin_loaded():
            self._add_process_stats_to_context(log_context)

        self._log_with_appropriate_level(log_context)

    def _add_process_stats_to_context(self, log_context: dict) -> None:
        """Add process statistics to log context."""
        process_stats = self._psutil_adapter.get_current_process_health_summary()
        if process_stats:
            log_context.update(process_stats)

    def _log_with_appropriate_level(self, log_context: dict) -> None:
        """Log health status with appropriate level based on resource usage."""
        memory_warning = self._check_memory_warning(log_context)
        cpu_warning = self._check_cpu_warning(log_context)
        bot_active = log_context.get("active", False)

        within_grace_period = self._is_within_startup_grace_period()

        if bot_active and not self._bot_fully_started:
            self._bot_fully_started = True
            with self.log_context(**log_context) as log:
                log.info("Bot successfully started and is now active")
            return

        with self.log_context(**log_context) as log:
            if memory_warning or cpu_warning:
                log.warning("High resource usage detected")
            elif not bot_active:
                if within_grace_period:
                    log.debug("Bot is starting up, not yet active")
                else:
                    log.error("Bot is not active")
            else:
                log.info("Health check completed")

    @staticmethod
    def _check_memory_warning(log_context: dict) -> bool:
        """Check if memory usage exceeds warning threshold."""
        memory_percent = log_context.get("memory_percent", "0%")
        if isinstance(memory_percent, str) and memory_percent.endswith("%"):
            try:
                return float(memory_percent[:-1]) > 80
            except ValueError:
                pass
        return False

    @staticmethod
    def _check_cpu_warning(log_context: dict) -> bool:
        """Check if CPU usage exceeds warning threshold."""
        cpu_percent = log_context.get("cpu", "0%")
        if isinstance(cpu_percent, str) and cpu_percent.endswith("%"):
            try:
                return float(cpu_percent[:-1]) > 90
            except ValueError:
                pass
        return False

    def _cleanup_bot(self) -> None:
        """Clean up bot resources."""
        if not self.bot:
            return

        try:
            self._stop_bot_operations()
        except Exception as e:
            with self.log_context(error=str(e)) as log:
                log.warning("Bot cleanup encountered issues")
        finally:
            self.bot = None

    def _wait_for_health_thread(self) -> None:
        """Wait for health check thread to complete."""
        if not (self.health_check_thread and self.health_check_thread.is_alive()):
            return

        self.health_check_thread.join(timeout=self.SHUTDOWN_TIMEOUT)

        if self.health_check_thread.is_alive():
            with self.log_context() as log:
                log.warning("Health check thread did not terminate gracefully")

    def shutdown(self) -> None:
        """Graceful shutdown with timeout."""
        with self._shutdown_lock:
            if not self.bot:
                return

            try:
                with self.log_context() as log:
                    log.info("Shutdown sequence initiated")

                self.shutdown_requested.set()
                self._stop_bot_operations()
                self._wait_for_health_thread()

                with self.log_context() as log:
                    log.info("Shutdown completed successfully")

            except Exception as e:
                with self.log_context(error=str(e)) as log:
                    log.error("Shutdown failed")

                raise ShutdownError(
                    ErrorContext(
                        message=f"Shutdown failed: {e}",
                        error_code="SHUTDOWN_001",
                        metadata={"exception": str(e), "type": type(e).__name__},
                    )
                )

    def validate_environment(self) -> None:
        """Validate runtime environment."""
        try:
            current_version = sys.version_info[:2]
            if current_version < self.MIN_PYTHON_VERSION:
                raise InitializationError(
                    ErrorContext(
                        message=f"Python {'.'.join(map(str, self.MIN_PYTHON_VERSION))}+ required, "
                        f"running {platform.python_version()}",
                        error_code="INIT_001",
                        metadata={"current_version": platform.python_version()},
                    )
                )

            # Only log environment info in debug mode
            with self.log_context(
                python_version=platform.python_version(),
                system=platform.system(),
            ) as log:
                log.debug("Environment validation completed")

        except Exception as e:
            raise InitializationError(
                ErrorContext(
                    message=f"Environment validation failed: {e}",
                    error_code="INIT_002",
                    metadata={"error": str(e), "type": type(e).__name__},
                )
            )

    def _register_signal_handler(self, sig: signal.Signals) -> None:
        """Register handler for a single signal."""
        try:
            signal.signal(sig, self._signal_handler)
        except (OSError, ValueError) as e:
            with self.log_context(signal=sig.name, error=str(e)) as log:
                log.debug(f"Cannot register signal handler: {e}")

    def _setup_signal_handlers(self) -> None:
        """Setup cross-platform signal handlers."""
        signal.signal(signal.SIGINT, self._signal_handler)

        signals_to_handle = [signal.SIGTERM]
        if hasattr(signal, "SIGHUP"):
            signals_to_handle.append(signal.SIGHUP)

        for sig in signals_to_handle:
            self._register_signal_handler(sig)

    def _start_health_monitoring(self) -> None:
        """Start health check monitoring thread."""
        self.health_check_thread = threading.Thread(
            target=self._health_check_loop, name="HealthMonitor", daemon=True
        )
        self.health_check_thread.start()

        with self.log_context(interval=self.HEALTH_CHECK_INTERVAL) as log:
            log.debug(f"Health monitoring started")

    def _run_main_loop(self) -> None:
        """Main execution loop with interruption handling."""
        with self._managed_bot() as bot:
            bot.launch_bot()

            # Main loop - wait for shutdown signal
            while not self.shutdown_requested.is_set():
                try:
                    if self.shutdown_requested.wait(timeout=self.MAIN_LOOP_TIMEOUT):
                        break
                except KeyboardInterrupt:
                    break

    def _get_error_context(self, error: Exception) -> dict[str, Any]:
        """Get comprehensive error context for logging."""
        health_status = HealthStatus()

        return {
            "exception_type": type(error).__name__,
            "exception_message": str(error),
            "traceback": traceback.format_exc(),
            "uptime": naturaltime(self.start_time),
            "last_health_check": health_status.last_health_check_result,
            "shutdown_requested": self.shutdown_requested.is_set(),
            "python_version": platform.python_version(),
            "system": platform.system(),
        }

    def _handle_keyboard_interrupt(self) -> NoReturn:
        """Handle keyboard interrupt gracefully."""
        with self.log_context() as log:
            log.info("Keyboard interrupt received, shutting down")
        try:
            self.shutdown()
        except ShutdownError as e:
            with self.log_context(error=str(e)) as log:
                log.error("Shutdown failed during keyboard interrupt handling")
        except Exception as e:
            with self.log_context(error=str(e), error_type=type(e).__name__) as log:
                log.warning("Unexpected error during keyboard interrupt shutdown")

        sys.exit(0)

    def _handle_fatal_error(self, error: Exception) -> NoReturn:
        """Handle fatal errors with comprehensive logging."""
        error_context = self._get_error_context(error)

        with self.log_context(**error_context) as log:
            log.critical("Fatal error occurred, initiating emergency shutdown")

        try:
            self.shutdown()
        except ShutdownError as e:
            with self.log_context(error=str(e)) as log:
                log.error("Shutdown failed during fatal error handling")
        except Exception as e:
            with self.log_context(error=str(e), error_type=type(e).__name__) as log:
                log.warning("Unexpected error during emergency shutdown")

        sys.exit(1)

    def run(self) -> NoReturn:
        """Main entry point with comprehensive error handling."""
        try:
            # Setup phase
            self._register_cleanup()
            self._setup_signal_handlers()
            self._start_health_monitoring()
            self.validate_environment()

            with self.log_context() as log:
                log.info("PyTMBot launcher initialization completed")

            # Main execution
            self._run_main_loop()
            self.shutdown()

            with self.log_context() as log:
                log.info("PyTMBot shutdown completed")

            sys.exit(0)

        except KeyboardInterrupt:
            self._handle_keyboard_interrupt()
        except Exception as e:
            self._handle_fatal_error(e)


def check_health() -> NoReturn:
    """Check bot health status and exit with appropriate code."""
    health_result = HealthStatus().last_health_check_result

    match health_result:
        case True:
            sys.exit(0)
        case False:
            sys.exit(1)
        case None:
            sys.exit(2)


def main() -> NoReturn:
    """Main entry point."""
    if args.health_check:
        check_health()
    else:
        BotLauncher().run()


if __name__ == "__main__":
    main()
