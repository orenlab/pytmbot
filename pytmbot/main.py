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
                if cls._instance is None:  # Double-checked locking
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
                    log.warning("Error stopping bot operations")

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
                with self.log_context(signal=sig_name, pid=os.getpid()) as log:
                    log.warning(
                        "Received SIGINT - initiating graceful shutdown (Ctrl+C again to force)"
                    )
                self.shutdown_requested.set()
            elif self._sigint_count >= 2:
                with self.log_context(
                    signal=sig_name, pid=os.getpid(), force=True
                ) as log:
                    log.warning("Received multiple SIGINT - forcing immediate shutdown")
                self._emergency_cleanup()
                # Restore default handler and re-raise signal
                signal.signal(signal.SIGINT, signal.SIG_DFL)
                os.kill(os.getpid(), signal.SIGINT)

    def _signal_handler(self, signum: int, frame) -> None:
        """Signal handler for graceful shutdown."""
        try:
            sig_name = signal.Signals(signum).name
        except ValueError:
            sig_name = f"Unknown signal {signum}"

        if signum == signal.SIGINT:
            self._handle_sigint(sig_name)
        else:
            with self.log_context(signal=sig_name, pid=os.getpid()) as log:
                log.warning("Received signal - initiating shutdown")
            self.shutdown_requested.set()
            self._stop_bot_operations()

    def _perform_health_check(self) -> bool:
        """Perform a single health check with error handling."""
        if not self.bot:
            return False

        try:
            is_healthy = self.bot.is_healthy()
            if not is_healthy:
                with self.log_context(recovery_attempt=True) as log:
                    log.warning("Bot unhealthy - attempting recovery")
                    if not self.bot.recovery():
                        log.error("Recovery failed")
            return is_healthy
        except Exception as e:
            with self.log_context(error=str(e)) as log:
                log.error("Health check error")
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

    def _log_health_status(self) -> None:
        """Log current health status with comprehensive process statistics."""
        uptime_display = naturaltime(self.start_time)

        log_context = {
            "uptime": uptime_display,
            "active": bool(self.bot),
            "pid": os.getpid(),
            "session_overview": self._session_manager.get_session_stats(),
        }

        if self._is_monitor_plugin_loaded():
            log_context["monitor_plugin_active"] = True
        else:
            self._add_process_stats_to_context(log_context)

        self._log_with_warnings(log_context)

    def _add_process_stats_to_context(self, log_context: dict) -> None:
        """Add process statistics to log context and check for warnings."""
        process_stats = self._psutil_adapter.get_current_process_health_summary()

        if process_stats:
            log_context.update(process_stats)
            self._check_resource_warnings(log_context, process_stats)
        else:
            log_context.update(
                {
                    "cpu": "N/A",
                    "memory_rss": "N/A",
                    "memory_percent": "N/A",
                    "status": "unknown",
                }
            )

    def _check_resource_warnings(self, log_context: dict, process_stats: dict) -> None:
        """Check for resource usage warnings and update log context."""
        if self._is_memory_warning(process_stats):
            log_context["memory_warning"] = True

        if self._is_cpu_warning(process_stats):
            log_context["cpu_warning"] = True

    @staticmethod
    def _is_memory_warning(process_stats: dict) -> bool:
        """Check if memory usage exceeds warning threshold."""
        if "memory_rss" not in process_stats or "memory_percent" not in process_stats:
            return False

        memory_percent_value = float(process_stats["memory_percent"].rstrip("%"))
        return memory_percent_value > 80

    @staticmethod
    def _is_cpu_warning(process_stats: dict) -> bool:
        """Check if CPU usage exceeds warning threshold."""
        if "cpu" not in process_stats:
            return False

        cpu_percent_value = float(process_stats["cpu"].rstrip("%"))
        return cpu_percent_value > 90

    def _log_with_warnings(self, log_context: dict) -> None:
        """Log health status with appropriate level based on warnings."""
        has_warnings = log_context.get("memory_warning") or log_context.get(
            "cpu_warning"
        )

        with self.log_context(**log_context) as log:
            if has_warnings:
                log.warning("Health check completed with resource warnings")
            else:
                log.debug("Health check completed")

    @contextmanager
    def _managed_bot(self) -> Generator[Any, None, None]:
        """Context manager for bot lifecycle."""
        try:
            self.bot = pytmbot_instance.PyTMBot()
            with self.log_context() as log:
                log.info("Bot instance created")
            yield self.bot
        except Exception as e:
            with self.log_context(error=str(e)) as log:
                log.error("Bot creation failed")
            raise
        finally:
            self._cleanup_bot()

    def _cleanup_bot(self) -> None:
        """Clean up bot resources."""
        if not self.bot:
            return

        try:
            with self.log_context() as log:
                log.info("Cleaning up bot instance")
            self._stop_bot_operations()
        except Exception as e:
            with self.log_context(error=str(e)) as log:
                log.warning("Bot cleanup error")
        finally:
            self.bot = None

    def _wait_for_health_thread(self) -> None:
        """Wait for health check thread to complete."""
        if not (self.health_check_thread and self.health_check_thread.is_alive()):
            return

        with self.log_context() as log:
            log.info("Waiting for health thread")

        self.health_check_thread.join(timeout=self.SHUTDOWN_TIMEOUT)

        if self.health_check_thread.is_alive():
            with self.log_context() as log:
                log.warning("Health thread timeout")

    def shutdown(self) -> None:
        """Graceful shutdown with timeout."""
        with self._shutdown_lock:
            if not self.bot:
                return

            try:
                with self.log_context() as log:
                    log.info("Starting shutdown sequence")

                self.shutdown_requested.set()
                self._stop_bot_operations()
                self._wait_for_health_thread()

                with self.log_context() as log:
                    log.info("Shutdown completed")

            except Exception as e:
                with self.log_context(error=str(e)) as log:
                    log.error("Shutdown error")

                error_metadata: dict[str, Any] = {
                    "exception": str(e),
                    "type": type(e).__name__,
                }
                raise ShutdownError(
                    ErrorContext(
                        message=f"Shutdown failed: {e}",
                        error_code="SHUTDOWN_001",
                        metadata=error_metadata,
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

            with self.log_context(
                python_version=platform.python_version(),
                system=platform.system(),
                platform=platform.platform(),
            ) as log:
                log.info("Environment validated")

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
            with self.log_context(signal=sig.name) as log:
                log.debug(f"Registered handler for {sig.name}")
        except (OSError, ValueError) as e:
            with self.log_context(signal=sig.name, error=str(e)) as log:
                log.warning(f"Cannot register {sig.name}: {e}")

    def _setup_signal_handlers(self) -> None:
        """Setup cross-platform signal handlers."""
        # Handle SIGINT with special logic for graceful vs forced shutdown
        signal.signal(signal.SIGINT, self._signal_handler)

        # Handle other termination signals
        signals_to_handle = [signal.SIGTERM]
        if hasattr(signal, "SIGHUP"):
            signals_to_handle.append(signal.SIGHUP)

        for sig in signals_to_handle:
            self._register_signal_handler(sig)

        with self.log_context() as log:
            log.debug(
                "Signal handlers registered (SIGINT: graceful->forced, others: immediate)"
            )

    def _start_health_monitoring(self) -> None:
        """Start health check monitoring thread."""
        self.health_check_thread = threading.Thread(
            target=self._health_check_loop, name="HealthMonitor", daemon=True
        )
        self.health_check_thread.start()

    def _run_main_loop(self) -> None:
        """Main execution loop with interruption handling."""
        with self._managed_bot() as bot:
            bot.launch_bot()

            # Main loop - wait for shutdown signal with regular checks
            while not self.shutdown_requested.is_set():
                try:
                    if self.shutdown_requested.wait(timeout=self.MAIN_LOOP_TIMEOUT):
                        break
                except KeyboardInterrupt:
                    # This should not normally happen since we handle SIGINT,
                    # but just in case
                    with self.log_context() as log:
                        log.info("KeyboardInterrupt in main loop")
                    break

            with self.log_context() as log:
                log.info("Main loop exiting")

    def _get_error_context(self, error: Exception) -> dict[str, Any]:
        """Get comprehensive error context for logging."""
        health_status = HealthStatus()

        return {
            "exception_type": type(error).__name__,
            "exception_value": str(error),
            "traceback": traceback.format_exc(),
            "shutdown_requested": self.shutdown_requested.is_set(),
            "last_health_check": health_status.last_health_check_result,
            "uptime": naturaltime(self.start_time),
            "active": bool(self.bot),
            "pid": os.getpid(),
            "python_version": platform.python_version(),
            "system": platform.system(),
            "platform": platform.platform(),
        }

    def _handle_keyboard_interrupt(self) -> NoReturn:
        """Handle keyboard interrupt gracefully."""
        with self.log_context() as log:
            log.info("KeyboardInterrupt - shutting down")
        try:
            self.shutdown()
        except Exception:
            pass
        sys.exit(0)

    def _handle_fatal_error(self, error: Exception) -> NoReturn:
        """Handle fatal errors with comprehensive logging."""
        error_context = self._get_error_context(error)

        with self.log_context(**error_context) as log:
            log.critical("Fatal error - emergency shutdown")

        try:
            self.shutdown()
        except Exception:
            pass

        sys.exit(1)

    def run(self) -> NoReturn:
        """Main entry point with comprehensive error handling."""
        try:
            # Setup
            self._register_cleanup()
            self._setup_signal_handlers()
            self._start_health_monitoring()
            self.validate_environment()

            with self.log_context(pid=os.getpid()) as log:
                log.info("Starting PyTMBot")

            # Main execution
            self._run_main_loop()
            self.shutdown()

            with self.log_context() as log:
                log.info("PyTMBot shutdown successfully")

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
            print("Bot is healthy")
            sys.exit(0)
        case False:
            print("Bot is unhealthy")
            sys.exit(1)
        case None:
            print("Health status unknown")
            sys.exit(2)


def main() -> NoReturn:
    """Main entry point."""
    if args.health_check:
        check_health()
    else:
        BotLauncher().run()


if __name__ == "__main__":
    main()
