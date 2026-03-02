#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Final, Protocol, override, runtime_checkable
from weakref import ReferenceType, ref

import telebot
from telebot.apihelper import ApiTelegramException

from pytmbot.logs import BaseComponent
from pytmbot.utils import to_float

RESOURCE_MEMORY_CRITICAL_THRESHOLD: Final[float] = 90.0
RESOURCE_MEMORY_UNHEALTHY_THRESHOLD: Final[float] = 80.0
RESOURCE_MEMORY_DEGRADED_THRESHOLD: Final[float] = 70.0
RESOURCE_CPU_CRITICAL_THRESHOLD: Final[float] = 95.0
RESOURCE_CPU_UNHEALTHY_THRESHOLD: Final[float] = 90.0
RESOURCE_CPU_DEGRADED_THRESHOLD: Final[float] = 80.0


class HealthLevel(IntEnum):
    """Health levels ordered by severity."""

    HEALTHY = 100
    DEGRADED = 75
    UNHEALTHY = 50
    CRITICAL = 25
    OFFLINE = 0

    def __str__(self) -> str:
        return self.name.lower()


@dataclass(frozen=True, slots=True)
class HealthResult:
    """Immutable health check result."""

    level: HealthLevel
    component: str
    latency_ms: float
    timestamp: float = field(default_factory=time.time)
    details: dict[str, object] = field(default_factory=dict)

    @property
    def is_operational(self) -> bool:
        return self.level >= HealthLevel.DEGRADED

    @property
    def needs_attention(self) -> bool:
        return self.level <= HealthLevel.UNHEALTHY


@dataclass(frozen=True, slots=True)
class SystemHealth:
    """Complete system health snapshot."""

    overall: HealthLevel
    components: dict[str, HealthResult]
    timestamp: float = field(default_factory=time.time)
    check_duration_ms: float = 0.0

    @property
    def operational_count(self) -> int:
        return sum(1 for r in self.components.values() if r.is_operational)

    @property
    def total_count(self) -> int:
        return len(self.components)

    @property
    def health_ratio(self) -> float:
        if not self.total_count:
            return 0.0
        healthy = sum(
            1 for r in self.components.values() if r.level == HealthLevel.HEALTHY
        )
        return healthy / self.total_count


class HealthChecker(Protocol):
    """Protocol for health checkers."""

    @property
    def name(self) -> str: ...

    @property
    def interval_seconds(self) -> float: ...

    def check_sync(self) -> HealthResult: ...


class SessionStatsProvider(Protocol):
    def get_session_stats(self) -> dict[str, int]: ...


class ProcessHealthAdapter(Protocol):
    def get_current_process_health_summary(self) -> dict[str, object]: ...


class _HealthCheckerRegistry(Protocol):
    def add_checker(self, checker: HealthChecker) -> None: ...


@runtime_checkable
class BotIdentity(Protocol):
    id: int
    username: str | None


class BaseHealthChecker(ABC):
    """Base class for health checkers with caching."""

    __slots__ = ("_cache_ttl", "_last_check", "_cached_result", "_lock")

    def __init__(self, cache_ttl: float = 30.0) -> None:
        self._cache_ttl = cache_ttl
        self._last_check: float = 0.0
        self._cached_result: HealthResult | None = None
        self._lock = threading.Lock()

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    def interval_seconds(self) -> float:
        return 60.0

    @abstractmethod
    def _perform_check(self) -> HealthResult:
        """Perform the actual health check - should be synchronous."""
        ...

    def check_sync(self) -> HealthResult:
        """Synchronous health check with caching."""
        current_time = time.time()

        # Return cached if valid
        if self._cached_result and (current_time - self._last_check) < self._cache_ttl:
            return self._cached_result

        with self._lock:
            # Double-check pattern
            if (
                self._cached_result
                and (current_time - self._last_check) < self._cache_ttl
            ):
                return self._cached_result

            start_time = time.perf_counter()
            try:
                result = self._perform_check()
            except Exception as e:
                latency = (time.perf_counter() - start_time) * 1000
                result = HealthResult(
                    level=HealthLevel.CRITICAL,
                    component=self.name,
                    latency_ms=latency,
                    details={"error": type(e).__name__, "message": str(e)},
                )

            self._cached_result = result
            self._last_check = current_time
            return result


class TelegramApiChecker(BaseHealthChecker):
    """Telegram API connectivity checker."""

    __slots__ = ("_bot_ref",)

    def __init__(self, bot_ref: ReferenceType[telebot.TeleBot]) -> None:
        super().__init__(cache_ttl=25.0)
        self._bot_ref = bot_ref

    @property
    def name(self) -> str:
        return "telegram_api"

    @property
    def interval_seconds(self) -> float:
        return 90.0

    @override
    def _perform_check(self) -> HealthResult:
        bot = self._bot_ref()
        if bot is None:
            return HealthResult(
                level=HealthLevel.OFFLINE,
                component=self.name,
                latency_ms=0.0,
                details={"error": "bot_unavailable"},
            )

        start_time = time.perf_counter()
        try:
            result: dict[str, object] = {}

            def api_call() -> None:
                try:
                    result["bot_info"] = bot.get_me()
                except Exception as error:
                    result["error"] = error

            thread = threading.Thread(
                target=api_call,
                name="HealthTelegramApiCheck",
                daemon=True,
            )
            thread.start()
            thread.join(timeout=5.0)
            if thread.is_alive():
                raise TimeoutError("API call timeout")

            error = result.get("error")
            if isinstance(error, Exception):
                raise error

            bot_info = result.get("bot_info")

            latency = (time.perf_counter() - start_time) * 1000

            if not bot_info:
                return HealthResult(
                    level=HealthLevel.CRITICAL,
                    component=self.name,
                    latency_ms=latency,
                    details={"error": "no_bot_info"},
                )

            # Determine level based on latency
            if latency > 3000:
                level = HealthLevel.DEGRADED
            else:
                level = HealthLevel.HEALTHY

            return HealthResult(
                level=level,
                component=self.name,
                latency_ms=latency,
                details=(
                    {
                        "bot_id": bot_info.id,
                        "username": bot_info.username or "unknown",
                    }
                    if isinstance(bot_info, BotIdentity)
                    else {"bot_id": "unknown", "username": "unknown"}
                ),
            )

        except (TimeoutError, OSError):
            latency = (time.perf_counter() - start_time) * 1000
            return HealthResult(
                level=HealthLevel.UNHEALTHY,
                component=self.name,
                latency_ms=latency,
                details={"error": "timeout"},
            )
        except ApiTelegramException as e:
            latency = (time.perf_counter() - start_time) * 1000

            if e.error_code in (401, 403, 404):
                level = HealthLevel.CRITICAL
            elif e.error_code in (409, 429):
                level = HealthLevel.DEGRADED
            else:
                level = HealthLevel.UNHEALTHY

            return HealthResult(
                level=level,
                component=self.name,
                latency_ms=latency,
                details={"error_code": e.error_code, "description": e.description},
            )


class PollingChecker(BaseHealthChecker):
    """Polling state checker."""

    __slots__ = ("_bot_ref",)

    def __init__(self, bot_ref: ReferenceType[telebot.TeleBot]) -> None:
        super().__init__(cache_ttl=15.0)
        self._bot_ref = bot_ref

    @property
    def name(self) -> str:
        return "polling"

    @property
    def interval_seconds(self) -> float:
        return 45.0

    @override
    def _perform_check(self) -> HealthResult:
        bot = self._bot_ref()
        if bot is None:
            return HealthResult(
                level=HealthLevel.OFFLINE,
                component=self.name,
                latency_ms=0.0,
                details={"error": "bot_unavailable"},
            )

        start_time = time.perf_counter()

        polling_active = bool(getattr(bot, "polling", False))
        polling_thread = getattr(bot, "polling_thread", None)
        polling_thread_alive: bool | None = None
        if polling_thread is not None:
            is_alive = getattr(polling_thread, "is_alive", None)
            if callable(is_alive):
                polling_thread_alive = bool(is_alive())

        latency = (time.perf_counter() - start_time) * 1000

        if not polling_active:
            level = HealthLevel.UNHEALTHY
            details: dict[str, object] = {"polling_active": False}
        elif polling_thread_alive is False:
            level = HealthLevel.CRITICAL
            details = {"polling_active": True, "polling_thread_alive": False}
        else:
            level = HealthLevel.HEALTHY
            details = {"polling_active": True}
            if polling_thread_alive:
                details["polling_thread_alive"] = True

        return HealthResult(
            level=level, component=self.name, latency_ms=latency, details=details
        )


class SystemResourceChecker(BaseHealthChecker):
    """System resource checker."""

    __slots__ = ("_psutil_adapter",)

    def __init__(self, psutil_adapter: ProcessHealthAdapter | None) -> None:
        super().__init__(cache_ttl=20.0)
        self._psutil_adapter = psutil_adapter

    @property
    def name(self) -> str:
        return "system_resources"

    @property
    def interval_seconds(self) -> float:
        return 75.0

    @override
    def _perform_check(self) -> HealthResult:
        if not self._psutil_adapter:
            return HealthResult(
                level=HealthLevel.OFFLINE,
                component=self.name,
                latency_ms=0.0,
                details={"error": "adapter_unavailable"},
            )

        start_time = time.perf_counter()

        try:
            stats = self._psutil_adapter.get_current_process_health_summary()
            latency = (time.perf_counter() - start_time) * 1000

            if not stats:
                return HealthResult(
                    level=HealthLevel.UNHEALTHY,
                    component=self.name,
                    latency_ms=latency,
                    details={"error": "no_stats"},
                )

            memory_percent = self._parse_percentage(stats.get("memory_percent", "0%"))
            cpu_percent = self._parse_percentage(stats.get("cpu", "0%"))

            if (
                memory_percent > RESOURCE_MEMORY_CRITICAL_THRESHOLD
                or cpu_percent > RESOURCE_CPU_CRITICAL_THRESHOLD
            ):
                level = HealthLevel.CRITICAL
            elif (
                memory_percent > RESOURCE_MEMORY_UNHEALTHY_THRESHOLD
                or cpu_percent > RESOURCE_CPU_UNHEALTHY_THRESHOLD
            ):
                level = HealthLevel.UNHEALTHY
            elif (
                memory_percent > RESOURCE_MEMORY_DEGRADED_THRESHOLD
                or cpu_percent > RESOURCE_CPU_DEGRADED_THRESHOLD
            ):
                level = HealthLevel.DEGRADED
            else:
                level = HealthLevel.HEALTHY

            return HealthResult(
                level=level,
                component=self.name,
                latency_ms=latency,
                details={
                    "memory_percent": memory_percent,
                    "cpu_percent": cpu_percent,
                    **stats,
                },
            )

        except Exception as e:
            latency = (time.perf_counter() - start_time) * 1000
            return HealthResult(
                level=HealthLevel.CRITICAL,
                component=self.name,
                latency_ms=latency,
                details={"error": str(e)},
            )

    @staticmethod
    def _parse_percentage(value: object) -> float:
        if isinstance(value, str) and not value.endswith("%"):
            return 0.0
        return to_float(value, 0.0, strip_percent=True)


class SessionChecker(BaseHealthChecker):
    """Session manager checker."""

    __slots__ = ("_session_manager",)

    def __init__(self, session_manager: SessionStatsProvider | None) -> None:
        super().__init__(cache_ttl=18.0)
        self._session_manager = session_manager

    @property
    def name(self) -> str:
        return "sessions"

    @property
    def interval_seconds(self) -> float:
        return 60.0

    @override
    def _perform_check(self) -> HealthResult:
        if not self._session_manager:
            return HealthResult(
                level=HealthLevel.OFFLINE,
                component=self.name,
                latency_ms=0.0,
                details={"error": "manager_unavailable"},
            )

        start_time = time.perf_counter()

        try:
            stats = self._session_manager.get_session_stats()
            latency = (time.perf_counter() - start_time) * 1000

            total = stats.get("total_sessions", 0)
            blocked = stats.get("blocked_sessions", 0)

            if total == 0:
                level = HealthLevel.HEALTHY
            else:
                blocked_ratio = blocked / total

                if blocked_ratio > 0.5:
                    level = HealthLevel.UNHEALTHY
                elif blocked_ratio > 0.3 or total > 1000:
                    level = HealthLevel.DEGRADED
                else:
                    level = HealthLevel.HEALTHY

            return HealthResult(
                level=level,
                component=self.name,
                latency_ms=latency,
                details=dict(stats),
            )

        except Exception as e:
            latency = (time.perf_counter() - start_time) * 1000
            return HealthResult(
                level=HealthLevel.CRITICAL,
                component=self.name,
                latency_ms=latency,
                details={"error": str(e)},
            )


class HealthMonitor(BaseComponent):
    """Central health monitoring system with proper lifecycle management."""

    __slots__ = (
        "_checkers",
        "_history",
        "_max_history",
        "_state_lock",
        "_running",
        "_latest",
        "_intervals",
        "_base_interval",
        "_thread",
        "_stop_event",
        "_monitor_failures",
        "_max_monitor_failures",
    )

    def __init__(self, max_history: int = 15) -> None:
        super().__init__("health_monitor")
        self._checkers: dict[str, HealthChecker] = {}
        self._history: deque[SystemHealth] = deque(maxlen=max_history)
        self._max_history = max_history
        self._state_lock = threading.RLock()
        self._running = False
        self._latest: SystemHealth | None = None
        self._intervals: dict[str, float] = {}
        self._base_interval = 120.0
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._monitor_failures = 0
        self._max_monitor_failures = 3

    def _publish_monitor_failure(self, error: Exception) -> None:
        """Publish internal monitor failure as health degradation signal."""
        now = time.time()
        with self._state_lock:
            latest_snapshot = self._latest
            consecutive_failures = self._monitor_failures
        components = dict(latest_snapshot.components) if latest_snapshot else {}
        components["health_monitor"] = HealthResult(
            level=HealthLevel.CRITICAL,
            component="health_monitor",
            latency_ms=0.0,
            details={
                "error": "monitor_loop_failed",
                "exception": str(error),
                "consecutive_failures": consecutive_failures,
            },
            timestamp=now,
        )

        health = SystemHealth(
            overall=min(result.level for result in components.values()),
            components=components,
            timestamp=now,
            check_duration_ms=0.0,
        )
        with self._state_lock:
            self._latest = health
            self._history.append(health)

    def add_checker(self, checker: HealthChecker) -> None:
        """Add health checker."""
        with self._state_lock:
            self._checkers[checker.name] = checker
            self._intervals[checker.name] = checker.interval_seconds

        with self.log_context(checker=checker.name) as log:
            log.trace("bot.health.added.checker.debug")

    def check_all(self) -> SystemHealth:
        """Perform health check on all components."""
        start_time = time.perf_counter()
        current_time = time.time()
        with self._state_lock:
            checkers_snapshot = list(self._checkers.items())
            intervals_snapshot = dict(self._intervals)
            latest_snapshot = self._latest

        # Determine which components need checking
        to_check = []
        for name, checker in checkers_snapshot:
            interval = intervals_snapshot.get(name, checker.interval_seconds)
            last_check = 0.0

            if latest_snapshot and name in latest_snapshot.components:
                last_check = latest_snapshot.components[name].timestamp

            if (current_time - last_check) >= interval:
                to_check.append((name, checker))

        # Use cached results if no checks needed
        if not to_check and latest_snapshot:
            return latest_snapshot

        # Start with previous results
        components = {}
        if latest_snapshot:
            components.update(latest_snapshot.components)

        # Update checked components
        for name, checker in to_check:
            try:
                components[name] = checker.check_sync()
            except Exception as e:
                components[name] = HealthResult(
                    level=HealthLevel.CRITICAL,
                    component=name,
                    latency_ms=0.0,
                    details={"error": "check_failed", "exception": str(e)},
                )

        # Calculate overall health
        if not components:
            overall = HealthLevel.OFFLINE
        else:
            levels = [r.level for r in components.values()]
            overall = min(levels)

            # Don't let one bad component drag everything down
            healthy_count = sum(1 for level in levels if level >= HealthLevel.DEGRADED)
            if overall == HealthLevel.UNHEALTHY and healthy_count >= len(levels) * 0.7:
                overall = HealthLevel.DEGRADED

        duration = (time.perf_counter() - start_time) * 1000

        health = SystemHealth(
            overall=overall,
            components=components,
            timestamp=current_time,
            check_duration_ms=duration,
        )

        with self._state_lock:
            self._history.append(health)
            self._latest = health

        return health

    def start_monitoring(self, base_interval: float = 120.0) -> None:
        """Start continuous monitoring in a separate thread."""
        with self._state_lock:
            if self._running:
                with self.log_context() as log:
                    log.warning("bot.health.monitoring.already.ok")
                return

            self._base_interval = base_interval
            self._running = True
            self._stop_event.clear()
            checker_count = len(self._checkers)
            thread = threading.Thread(
                target=self._monitor_loop, name="HealthMonitor", daemon=True
            )
            self._thread = thread

        thread.start()
        with self.log_context(checkers=checker_count, interval=base_interval) as log:
            log.info("bot.health.monitoring.start")

    def stop_monitoring(self) -> None:
        """Stop monitoring."""
        with self._state_lock:
            if not self._running:
                return

            self._running = False
            self._stop_event.set()
            thread = self._thread

        if thread and thread.is_alive():
            thread.join(timeout=5.0)

        with self.log_context() as log:
            log.info("bot.health.monitoring.stop")

    def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        with self.log_context() as log:
            log.trace("bot.health.monitoring.loop.start")

        previous_level: HealthLevel | None = None

        while True:
            with self._state_lock:
                is_running = self._running
                base_interval = self._base_interval
            if not is_running or self._stop_event.is_set():
                break

            try:
                health = self.check_all()
                is_first_check = previous_level is None
                has_changed = (
                    previous_level is not None and previous_level != health.overall
                )

                if is_first_check:
                    log_method = "info"
                elif has_changed:
                    if health.overall == HealthLevel.HEALTHY:
                        log_method = "info"
                    elif health.overall in (
                        HealthLevel.DEGRADED,
                        HealthLevel.UNHEALTHY,
                    ):
                        log_method = "warning"
                    else:
                        log_method = "error"
                elif health.overall == HealthLevel.HEALTHY:
                    log_method = "trace"
                elif health.overall in (HealthLevel.DEGRADED, HealthLevel.UNHEALTHY):
                    log_method = "warning"
                else:
                    log_method = "error"

                with self.log_context(
                    overall=str(health.overall),
                    operational=health.operational_count,
                    total=health.total_count,
                    health_ratio=f"{health.health_ratio:.1%}",
                    duration_ms=f"{health.check_duration_ms:.1f}",
                ) as log:
                    if is_first_check:
                        event = "bot.health.monitoring.initial.status"
                    elif has_changed and health.overall == HealthLevel.HEALTHY:
                        event = "bot.health.monitoring.recovered.status"
                    else:
                        event = "bot.health.monitoring.status"
                    getattr(log, log_method)(event)

                # Adaptive interval
                if health.overall <= HealthLevel.UNHEALTHY:
                    interval = base_interval * 0.5
                elif health.overall == HealthLevel.DEGRADED:
                    interval = base_interval * 0.75
                else:
                    interval = base_interval

                previous_level = health.overall
                with self._state_lock:
                    self._monitor_failures = 0

            except Exception as e:
                with self._state_lock:
                    self._monitor_failures += 1
                    failures = self._monitor_failures
                    interval = self._base_interval
                self._publish_monitor_failure(e)
                with self.log_context(error=str(e)) as log:
                    log.error("bot.health.monitoring.fail")
                    if failures >= self._max_monitor_failures:
                        log.critical("bot.health.monitoring.degraded.fail")

            # Sleep with early exit
            self._stop_event.wait(timeout=interval)

        with self.log_context() as log:
            log.debug("bot.health.monitoring.loop.debug")

    @property
    def checker_count(self) -> int:
        """Get the number of registered checkers."""
        with self._state_lock:
            return len(self._checkers)

    @property
    def latest(self) -> SystemHealth | None:
        """Get latest health status."""
        with self._state_lock:
            return self._latest

    @property
    def is_healthy(self) -> bool:
        """Quick health check."""
        with self._state_lock:
            latest = self._latest
        return latest is not None and latest.overall >= HealthLevel.DEGRADED

    def get_summary(self) -> dict[str, object]:
        """Get health summary for logging."""
        with self._state_lock:
            latest = self._latest

        if not latest:
            return {"status": "no_data"}

        return {
            "overall": str(latest.overall),
            "health_ratio": latest.health_ratio,
            "operational": latest.operational_count,
            "total": latest.total_count,
            "duration_ms": latest.check_duration_ms,
            "components": {
                name: {
                    "level": str(result.level),
                    "latency_ms": result.latency_ms,
                    "details": result.details,
                }
                for name, result in latest.components.items()
            },
        }


class HealthManager:
    """Simplified health manager that uses threading instead of asyncio."""

    __slots__ = ("_monitor", "_started")

    def __init__(self, max_history: int = 15):
        self._monitor = HealthMonitor(max_history)
        self._started = False

    def add_checker(self, checker: HealthChecker) -> None:
        """Add health checker."""
        self._monitor.add_checker(checker)

    def start(self, base_interval: float = 120.0) -> None:
        """Start health monitoring."""
        if self._started:
            return

        try:
            self._monitor.start_monitoring(base_interval)
            self._started = True
        except Exception as e:
            with self._monitor.log_context(error=str(e)) as log:
                log.error("bot.health.start.monitoring.fail")
            raise

    def stop(self, timeout: float = 5.0) -> None:
        """Stop health monitoring."""
        if not self._started:
            return

        try:
            self._monitor.stop_monitoring()
            self._started = False
        except Exception as e:
            with self._monitor.log_context(error=str(e)) as log:
                log.error("bot.health.stop.monitoring.fail")

    @property
    def is_healthy(self) -> bool:
        """Quick health check."""
        return self._monitor.is_healthy

    def get_summary(self) -> dict[str, object]:
        """Get health summary."""
        return self._monitor.get_summary()

    @property
    def monitor(self) -> HealthMonitor:
        return self._monitor


# Factory functions
def _configure_health_checks(
    target: _HealthCheckerRegistry,
    bot: telebot.TeleBot,
    session_manager: SessionStatsProvider | None = None,
    psutil_adapter: ProcessHealthAdapter | None = None,
) -> None:
    """Register core health checkers for monitor/manager factories."""
    bot_ref = ref(bot)
    target.add_checker(TelegramApiChecker(bot_ref))
    target.add_checker(PollingChecker(bot_ref))

    if session_manager:
        target.add_checker(SessionChecker(session_manager))

    if psutil_adapter:
        target.add_checker(SystemResourceChecker(psutil_adapter))

    try:
        from pytmbot.parsers.health_checker import TemplateParserChecker

        target.add_checker(TemplateParserChecker())
    except ImportError:
        pass  # Parser не доступен


def create_health_monitor(
    bot: telebot.TeleBot,
    session_manager: SessionStatsProvider | None = None,
    psutil_adapter: ProcessHealthAdapter | None = None,
) -> HealthMonitor:
    """Create configured health monitor."""
    monitor = HealthMonitor()
    _configure_health_checks(monitor, bot, session_manager, psutil_adapter)
    return monitor


def create_health_manager(
    bot: telebot.TeleBot,
    session_manager: SessionStatsProvider | None = None,
    psutil_adapter: ProcessHealthAdapter | None = None,
) -> HealthManager:
    """Create configured health manager."""
    manager = HealthManager()
    _configure_health_checks(manager, bot, session_manager, psutil_adapter)
    return manager


# Legacy compatibility
class HealthStatus:
    """Legacy compatibility singleton."""

    __slots__ = ("_manager", "_state_lock", "_initialized")

    _instance: HealthStatus | None = None
    _instance_lock = threading.RLock()

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._manager: HealthManager | None = None
        self._state_lock = threading.RLock()
        self._initialized = True

    def __new__(cls) -> HealthStatus:
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def set_manager(self, manager: HealthManager) -> None:
        """Set health manager."""
        with self._state_lock:
            self._manager = manager

    @property
    def last_health_check_result(self) -> bool | None:
        """Legacy property."""
        with self._state_lock:
            if not self._manager:
                return None
            return self._manager.is_healthy

    @last_health_check_result.setter
    def last_health_check_result(self, value: bool | None) -> None:
        """Legacy setter - no-op."""
        pass

    def update_health(self, is_healthy: bool) -> None:
        """Legacy method - no-op."""
        pass

    def get_summary(self) -> dict[str, object]:
        """Return latest health summary for UI consumers."""
        with self._state_lock:
            manager = self._manager
        if manager is None:
            return {"status": "no_data"}
        return manager.get_summary()
