#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import atexit
import os
import platform
import signal
import sys
import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from datetime import datetime
from types import FrameType
from typing import TYPE_CHECKING, Final, NoReturn

from humanize import naturaltime

from pytmbot import logs
from pytmbot.adapters.docker.client import reset_docker_client_context
from pytmbot.adapters.psutil.adapter import PsutilAdapter
from pytmbot.exceptions import ErrorContext, InitializationError, ShutdownError
from pytmbot.health_system import HealthManager, HealthStatus, create_health_manager
from pytmbot.middleware.session_manager import SessionManager
from pytmbot.utils import parse_cli_args

args = parse_cli_args()

if TYPE_CHECKING:
    from telebot import TeleBot

    from pytmbot.pytmbot_instance import PyTMBot


class BotLauncher(logs.BaseComponent):
    """Main bot launcher with professional health system integration."""

    SHUTDOWN_TIMEOUT: Final[int] = 10
    MIN_PYTHON_VERSION: Final[tuple[int, int]] = (3, 12)
    MAIN_LOOP_TIMEOUT: Final[float] = 0.5
    STARTUP_GRACE_PERIOD: Final[int] = 30
    HEALTH_LOG_INTERVAL: Final[int] = 60  # Log health every 60 seconds
    POLLING_RESTART_MAX_ATTEMPTS: Final[int] = 3
    POLLING_RESTART_BACKOFF_SECONDS: Final[int] = 2
    INITIAL_HEALTH_WAIT_TIMEOUT_SECONDS: Final[float] = 0.5

    def __init__(self) -> None:
        super().__init__("bot_launcher")
        self.bot: PyTMBot | None = None
        self.shutdown_requested = threading.Event()
        self.start_time = datetime.now()
        self._start_monotonic = time.monotonic()
        self._shutdown_lock = threading.RLock()
        self._shutdown_completed = False
        self._bot_operations_stopped = False
        self._cleanup_registered = False
        self._sigint_count = 0
        self._sigint_lock = threading.Lock()
        self._psutil_adapter = PsutilAdapter()
        self._session_manager = SessionManager()
        self._bot_fully_started = False

        # Professional health system
        self._health_manager: HealthManager | None = None
        self._last_health_log = 0.0
        self._previous_health_level: str | None = None
        self._initial_health_logged = False

    def _register_cleanup(self) -> None:
        """Register cleanup handler to ensure proper shutdown on exit."""
        if not self._cleanup_registered:
            atexit.register(self._emergency_cleanup)
            self._cleanup_registered = True

    def _shutdown_bot_silently(self, *, silent: bool) -> None:
        """Stop polling and remove webhook with optional error handling."""
        with self._shutdown_lock:
            if self._bot_operations_stopped:
                return
            self._bot_operations_stopped = True

        try:
            if self.bot and hasattr(self.bot, "bot") and self.bot.bot:
                stop_polling: Callable[[], object] = self.bot.bot.stop_polling
                stop_polling()
                self.bot.bot.remove_webhook()
            self._session_manager.shutdown()
            reset_docker_client_context()
        except Exception as e:
            if not silent:
                with self.log_context(error=str(e)) as log:
                    log.warning("bot.launcher.encountered.issues.stop")

    def _emergency_cleanup(self) -> None:
        """Emergency cleanup for atexit - minimal operations only."""
        self._stop_health_system()
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
                    log.info("bot.launcher.graceful.stop")
                self.shutdown_requested.set()
            elif self._sigint_count >= 2:
                with self.log_context(signal=sig_name) as log:
                    log.warning("bot.launcher.forced.stop")
                self._emergency_cleanup()
                signal.signal(signal.SIGINT, signal.SIG_DFL)
                os.kill(os.getpid(), signal.SIGINT)

    def _signal_handler(self, signum: int, frame: FrameType | None) -> None:
        """Signal handler for graceful shutdown."""
        _ = frame
        try:
            sig_name = signal.Signals(signum).name
        except ValueError:
            sig_name = f"signal_{signum}"

        if signum == signal.SIGINT:
            self._handle_sigint(sig_name)
        else:
            with self.log_context(signal=sig_name) as log:
                log.info("bot.launcher.initiated.signal.stop")
            self.shutdown_requested.set()

    @contextmanager
    def _managed_bot(self) -> Generator[PyTMBot, None, None]:
        """Context manager for bot lifecycle."""
        try:
            from pytmbot.pytmbot_instance import PyTMBot

            self.bot = PyTMBot()
            yield self.bot
        except Exception as e:
            with self.log_context(error=str(e)) as log:
                log.error("bot.launcher.creation.fail")
            raise
        finally:
            self._cleanup_bot()

    def setup_health_system(self) -> None:
        """Setup professional health monitoring system."""
        bot_component = self.bot
        if bot_component is None or bot_component.bot is None:
            with self.log_context() as log:
                log.warning("bot.launcher.cannot.init.ok")
            return

        try:
            self._health_manager = create_health_manager(
                bot=bot_component.bot,
                session_manager=self._session_manager,
                psutil_adapter=self._psutil_adapter,
            )

            # Update legacy singleton for compatibility
            health_status = HealthStatus()
            health_status.set_manager(self._health_manager)

            with self.log_context(
                components=self._health_manager.monitor.checker_count
            ) as log:
                log.info("bot.launcher.health.monitoring.init")

        except Exception as e:
            with self.log_context(error=str(e)) as log:
                log.error("bot.launcher.init.health.fail")
            # Don't re-raise - health system failure shouldn't prevent bot startup

    def start_health_monitoring(self) -> None:
        """Start health monitoring."""
        if not self._health_manager:
            with self.log_context() as log:
                log.warning("bot.launcher.cannot.start.init")
            return

        try:
            self._health_manager.start(base_interval=120.0)

        except Exception as e:
            with self.log_context(error=str(e)) as log:
                log.error("bot.launcher.start.health.fail")

    def _wait_for_initial_health(self, timeout_seconds: float) -> None:
        """Wait briefly for first health snapshot without blocking startup for long."""
        if not self._health_manager or timeout_seconds <= 0:
            return

        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            health_summary = self._health_manager.get_summary()
            if health_summary.get("status") != "no_data":
                return
            time.sleep(0.05)

    def _stop_health_system(self) -> None:
        """Stop health monitoring system."""
        if self._health_manager:
            try:
                self._health_manager.stop(timeout=5.0)
                with self.log_context() as log:
                    log.info("bot.launcher.health.monitoring.stop")
            except Exception as e:
                with self.log_context(error=str(e)) as log:
                    log.warning("bot.launcher.stop.health.fail")
            finally:
                self._health_manager = None

    def _is_within_startup_grace_period(self) -> bool:
        """Check if we're still within the startup grace period."""
        uptime_seconds = time.monotonic() - self._start_monotonic
        return uptime_seconds < self.STARTUP_GRACE_PERIOD

    def _should_log_health_status(self) -> bool:
        """Check if we should log health status based on interval and health state."""
        if not self._health_manager:
            return False

        current_time = time.time()
        current_summary = self._health_manager.get_summary()
        current_overall = str(current_summary.get("overall", "offline"))

        if (
            self._previous_health_level is None
            or current_overall != self._previous_health_level
        ):
            self._last_health_log = current_time
            return True

        if (current_time - self._last_health_log) >= self.HEALTH_LOG_INTERVAL:
            self._last_health_log = current_time
            return True
        return False

    def log_health_status(self) -> None:
        """Log current health status using professional system with optimized output."""
        if not self._health_manager:
            return

        health_summary = self._health_manager.get_summary()
        overall_value = health_summary.get("overall")
        overall_status = overall_value if isinstance(overall_value, str) else "offline"
        has_state_changed = (
            self._previous_health_level is not None
            and self._previous_health_level != overall_status
        )
        is_first_health_check = not self._initial_health_logged

        # Get supporting data only when needed
        uptime_display = naturaltime(self.start_time)
        bot_session_metrics = None
        if self.bot and hasattr(self.bot, "get_bot_session_statistics"):
            bot_session_metrics = self.bot.get_bot_session_statistics()

        within_grace_period = self._is_within_startup_grace_period()

        # Handle startup completion
        if not self._bot_fully_started and self.bot:
            self._bot_fully_started = True
            self._log_bot_startup_completion(
                health_summary, uptime_display, bot_session_metrics
            )
            self._previous_health_level = overall_status
            self._initial_health_logged = True
            return

        # Determine log level
        log_level = self._determine_health_log_level(
            overall_status,
            within_grace_period,
            has_state_changed,
            is_first_health_check,
        )

        # Main health status log - concise and focused
        self._log_main_health_status(
            overall_status, health_summary, uptime_display, log_level
        )

        # Additional details only in debug mode or when there are issues
        if args.log_level == "DEBUG" or overall_status not in ("healthy", "degraded"):
            self._log_health_details(health_summary, bot_session_metrics)

        self._previous_health_level = overall_status
        self._initial_health_logged = True

    def _log_bot_startup_completion(
        self,
        health_summary: dict[str, object],
        uptime_display: str,
        bot_session_metrics: dict[str, object] | None,
    ) -> None:
        """Log bot startup completion with essential metrics."""
        log_context = {
            "overall": health_summary.get("overall", "unknown"),
            "components": f"{health_summary.get('operational', 0)}/{health_summary.get('total', 0)}",
            "uptime": uptime_display,
            "session_id": bot_session_metrics.get("session_id")
            if bot_session_metrics
            else "unknown",
            "mode": self._normalize_mode_value(bot_session_metrics.get("mode"))
            if bot_session_metrics
            else "unknown",
        }

        with self.log_context(**log_context) as log:
            log.info("bot.launcher.start.ok")

    def _determine_health_log_level(
        self,
        overall_status: str,
        within_grace_period: bool,
        has_state_changed: bool,
        is_first_health_check: bool,
    ) -> str:
        """Determine appropriate log level for health status."""
        if is_first_health_check:
            return "info"

        if has_state_changed:
            if overall_status == "healthy":
                return "info"
            if overall_status in ("degraded", "unhealthy"):
                return "warning"
            return "error"

        if overall_status in ("critical", "offline"):
            return "error"
        if overall_status in ("unhealthy", "degraded"):
            return "warning"
        if not self.bot:
            return "debug" if within_grace_period else "error"
        if overall_status == "healthy":
            return "trace"
        return "info"

    def _log_main_health_status(
        self,
        overall_status: str,
        health_summary: dict[str, object],
        uptime_display: str,
        log_level: str,
    ) -> None:
        """Log main health status with key metrics."""
        raw_components = health_summary.get("components")
        components = raw_components if isinstance(raw_components, dict) else {}

        # Create component status summary
        component_status = {}
        critical_issues = []

        for name, component in components.items():
            if not isinstance(component, dict):
                continue
            level = component.get("level", "unknown")
            latency = component.get("latency_ms", 0)

            if level == "critical":
                critical_issues.append(name)

            # Simplified component status
            if name == "telegram_api":
                component_status["api"] = (
                    f"{latency:.0f}ms" if level == "healthy" else level
                )
            elif name == "polling":
                component_status["polling"] = "OK" if level == "healthy" else level
            elif name == "sessions":
                session_details = component.get("details", {})
                total = session_details.get("total_sessions", 0)
                component_status["sessions"] = (
                    f"{total}" if level == "healthy" else f"{total}({level})"
                )
            elif name == "system_resources":
                sys_details = component.get("details", {})
                mem = sys_details.get("memory_percent", "0%")
                cpu = sys_details.get("cpu_percent", 0)
                component_status["resources"] = (
                    f"{mem}/CPU:{cpu:.1f}%" if level == "healthy" else level
                )

        # Main status log
        log_context = {
            "overall": overall_status.upper(),
            "components": f"{health_summary.get('operational', 0)}/{health_summary.get('total', 0)}",
            "health_ratio": f"{health_summary.get('health_ratio', 0):.0%}",
            "check_duration": f"{health_summary.get('duration_ms', 0):.0f}ms",
            "uptime": uptime_display,
            **component_status,
        }

        # Add critical issues if any
        if critical_issues:
            log_context["critical_components"] = critical_issues

        with self.log_context(**log_context) as log:
            getattr(log, log_level)("bot.launcher.health.status")

    @staticmethod
    def _normalize_mode_value(mode: object) -> str:
        """Normalize enum-like mode values for compact log output."""
        return str(getattr(mode, "value", mode))

    @staticmethod
    def _normalize_bool_flag(value: object) -> bool:
        """Normalize CLI boolean-like values to strict bool."""
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"true", "1", "yes", "on"}

    def _log_health_details(
        self,
        health_summary: dict[str, object],
        bot_session_metrics: dict[str, object] | None,
    ) -> None:
        """Log detailed health information when needed."""
        raw_components = health_summary.get("components")
        components = raw_components if isinstance(raw_components, dict) else {}

        # Log component details for non-healthy components
        unhealthy_components: dict[str, dict[str, object]] = {
            name: component
            for name, component in components.items()
            if isinstance(component, dict)
            and component.get("level") not in ("healthy",)
        }

        if unhealthy_components:
            for name, component in unhealthy_components.items():
                details = component.get("details", {})
                with self.log_context(
                    health_component=name,
                    level=component.get("level"),
                    latency_ms=f"{component.get('latency_ms', 0):.1f}",
                    details=details,
                ) as log:
                    log.debug("bot.launcher.component.issue.debug")

        # Log session and rate limit stats only if there's activity
        if bot_session_metrics:
            rate_stats_raw = bot_session_metrics.get("rate_limit_stats", {})
            rate_stats = rate_stats_raw if isinstance(rate_stats_raw, dict) else {}
            active_users_raw = rate_stats.get("active_users", 0)
            total_violations_raw = rate_stats.get("total_violations", 0)
            active_users = active_users_raw if isinstance(active_users_raw, int) else 0
            total_violations = (
                total_violations_raw if isinstance(total_violations_raw, int) else 0
            )

            if active_users > 0 or total_violations > 0:
                with self.log_context(
                    active_users=active_users,
                    rate_violations=total_violations,
                ) as log:
                    log.debug("bot.launcher.user.activity.debug")

        # System resource details only if concerning
        system_component = components.get("system_resources", {})
        if system_component.get("level") != "healthy":
            sys_details = system_component.get("details", {})
            with self.log_context(
                cpu_percent=sys_details.get("cpu_percent", 0),
                memory_percent=sys_details.get("memory_percent", "0%"),
                memory_rss=sys_details.get("memory_rss", "0"),
                threads=sys_details.get("threads", 0),
                status=sys_details.get("status", "unknown"),
            ) as log:
                log.debug("bot.launcher.resource.details.debug")

    @staticmethod
    def _is_monitor_plugin_loaded() -> bool:
        try:
            from pytmbot.plugins.plugin_manager import PluginManager

            return PluginManager.is_plugin_loaded("monitor")
        except ImportError:
            return False

    def _cleanup_bot(self) -> None:
        """Clean up bot resources."""
        if not self.bot:
            return
        self.bot = None

    def shutdown(self) -> None:
        """Graceful shutdown with timeout."""
        with self._shutdown_lock:
            if self._shutdown_completed:
                return
            if (
                not self.bot
                and not self._health_manager
                and self._bot_operations_stopped
            ):
                self._shutdown_completed = True
                return

            try:
                with self.log_context() as log:
                    log.info("bot.launcher.sequence.initiated.stop")

                self.shutdown_requested.set()
                self._stop_health_system()
                self._stop_bot_operations()

                with self.log_context() as log:
                    log.info("bot.launcher.stop.ok")
                self._shutdown_completed = True

            except Exception as e:
                with self.log_context(error=str(e)) as log:
                    log.error("bot.launcher.stop.fail")

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

            with self.log_context(
                python_version=platform.python_version(),
                system=platform.system(),
            ) as log:
                log.debug("bot.launcher.environment.validation.ok")

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
                log.debug("bot.launcher.cannot.register.debug")

    def _setup_signal_handlers(self) -> None:
        """Setup cross-platform signal handlers."""
        signal.signal(signal.SIGINT, self._signal_handler)

        signals_to_handle = [signal.SIGTERM]
        if hasattr(signal, "SIGHUP"):
            signals_to_handle.append(signal.SIGHUP)

        for sig in signals_to_handle:
            self._register_signal_handler(sig)

    def run_main_loop(self) -> None:
        """Main execution loop with health system integration."""
        with self._managed_bot() as bot:
            # Initialize bot core but don't start polling yet
            with self.log_context() as log:
                log.debug("bot.launcher.init")
            bot_instance = bot.initialize_bot_core()

            # Setup health system while bot is initialized but not polling
            self.setup_health_system()

            # Start health monitoring
            self.start_health_monitoring()

            self._wait_for_initial_health(self.INITIAL_HEALTH_WAIT_TIMEOUT_SECONDS)

            # Log initial health status
            if self._health_manager:
                self.log_health_status()

            # Now start the actual bot polling (this will block)
            # Start polling in a separate thread so we can monitor it
            polling_thread = threading.Thread(
                target=self._start_bot_polling,
                args=(bot_instance,),
                name="BotPolling",
                daemon=True,
            )
            polling_thread.start()
            polling_restart_attempts = 0

            # Main monitoring loop - wait for shutdown signal
            while not self.shutdown_requested.is_set():
                try:
                    if not polling_thread.is_alive():
                        if (
                            polling_restart_attempts
                            >= self.POLLING_RESTART_MAX_ATTEMPTS
                        ):
                            with self.log_context(
                                restart_attempts=polling_restart_attempts
                            ) as log:
                                log.error("bot.launcher.polling.restart.exceeded.fail")
                            self.shutdown_requested.set()
                            break

                        polling_restart_attempts += 1
                        with self.log_context(
                            restart_attempt=polling_restart_attempts,
                            max_attempts=self.POLLING_RESTART_MAX_ATTEMPTS,
                        ) as log:
                            log.warning("bot.launcher.polling.restarted.warn")

                        time.sleep(self.POLLING_RESTART_BACKOFF_SECONDS)
                        polling_thread = threading.Thread(
                            target=self._start_bot_polling,
                            args=(bot_instance,),
                            name="BotPolling",
                            daemon=True,
                        )
                        polling_thread.start()
                        continue

                    # Periodic health status logging
                    if self._should_log_health_status():
                        self.log_health_status()

                    if self.shutdown_requested.wait(timeout=self.MAIN_LOOP_TIMEOUT):
                        break
                except KeyboardInterrupt:
                    break

    def _start_bot_polling(self, bot_instance: TeleBot) -> None:
        """Start bot polling in a separate method."""
        try:
            webhook_enabled = self._normalize_bool_flag(args.webhook)
            bot_component = self.bot
            if bot_component is None:
                raise RuntimeError("Bot component is not initialized")

            with self.log_context(
                webhook_enabled=webhook_enabled,
                mode=self._normalize_mode_value(args.mode),
            ) as log:
                log.info("bot.launcher.start")

            bot_instance.remove_webhook()
            if webhook_enabled:
                try:
                    bot_component._start_webhook_server()
                except Exception as webhook_error:
                    with self.log_context(
                        error=str(webhook_error),
                        fallback_mode="polling",
                    ) as log:
                        log.warning("bot.launcher.webhook.failover.polling.warn")
                    bot_component._start_polling_loop(bot_instance)
            else:
                bot_component._start_polling_loop(bot_instance)
        except Exception as error:
            with self.log_context(error=str(error)) as log:
                log.error("bot.launcher.polling.fail")
            self.shutdown_requested.set()

    def _handle_keyboard_interrupt(self) -> None:
        """Handle keyboard interrupt gracefully."""
        with self.log_context() as log:
            log.info("bot.launcher.keyboard.interrupt.info")
        try:
            self.shutdown()
        except ShutdownError as e:
            with self.log_context(error=str(e)) as log:
                log.error("bot.launcher.stop.fail")
        except Exception as e:
            with self.log_context(error=str(e), error_type=type(e).__name__) as log:
                log.warning("bot.launcher.unexpected.fail")

    def _handle_fatal_error(self, error: Exception) -> NoReturn:
        """Handle fatal errors with comprehensive logging."""
        error_context = {
            "exception_type": type(error).__name__,
            "exception_message": str(error),
            "uptime": naturaltime(self.start_time),
            "shutdown_requested": self.shutdown_requested.is_set(),
            "python_version": platform.python_version(),
            "system": platform.system(),
        }

        with self.log_context(**error_context) as log:
            log.critical("bot.launcher.initiate.fail")

        try:
            self.shutdown()
        except ShutdownError as e:
            with self.log_context(error=str(e)) as log:
                log.error("bot.launcher.stop.fail")
        except Exception as e:
            with self.log_context(error=str(e), error_type=type(e).__name__) as log:
                log.warning("bot.launcher.unexpected.fail")

        sys.exit(1)

    def run(self) -> None:
        """Main entry point with comprehensive error handling."""
        try:
            # Setup phase
            self._register_cleanup()
            self._setup_signal_handlers()
            self.validate_environment()

            with self.log_context() as log:
                log.info("bot.launcher.init.start.ok")

            # Main execution
            self.run_main_loop()
            self.shutdown()

        except KeyboardInterrupt:
            self._handle_keyboard_interrupt()
        except Exception as e:
            self._handle_fatal_error(e)


def check_health() -> NoReturn:
    """Check bot health status and exit with appropriate code."""
    health_status = HealthStatus()
    result = health_status.last_health_check_result

    match result:
        case True:
            sys.exit(0)
        case False:
            sys.exit(1)
        case None:
            sys.exit(2)


def main() -> None:
    """Main entry point."""
    if args.health_check:
        check_health()
    else:
        BotLauncher().run()


if __name__ == "__main__":
    main()
