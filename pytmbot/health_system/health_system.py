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
from typing import Any, Protocol
from typing import override
from weakref import ref, ReferenceType

import telebot
from telebot.apihelper import ApiTelegramException

from pytmbot.logs import BaseComponent


class HealthLevel(IntEnum):
    """Health levels ordered by severity."""

    HEALTHY = 100
    DEGRADED = 75
    UNHEALTHY = 50
    CRITICAL = 25
    OFFLINE = 0

    def __str__(self) -> str:
        return self.name.lower()


@dataclass(frozen=True)
class HealthResult:
    """Immutable health check result."""

    level: HealthLevel
    component: str
    latency_ms: float
    timestamp: float = field(default_factory=time.time)
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def is_operational(self) -> bool:
        return self.level >= HealthLevel.DEGRADED

    @property
    def needs_attention(self) -> bool:
        return self.level <= HealthLevel.UNHEALTHY


@dataclass(frozen=True)
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


class BaseHealthChecker(ABC):
    """Base class for health checkers with caching."""

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
            # Use a simple timeout approach instead of signals
            import concurrent.futures
            import threading

            def api_call():
                return bot.get_me()

            # Use ThreadPoolExecutor with timeout
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(api_call)
                try:
                    bot_info = future.result(timeout=5.0)
                except concurrent.futures.TimeoutError:
                    raise TimeoutError("API call timeout")

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
                details={"bot_id": bot_info.id, "username": bot_info.username},
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

        polling_active = getattr(bot, "polling", False)
        polling_thread = getattr(bot, "_TeleBot__polling_thread", None)

        latency = (time.perf_counter() - start_time) * 1000

        if not polling_active:
            level = HealthLevel.UNHEALTHY
            details = {"polling_active": False}
        elif polling_thread and not polling_thread.is_alive():
            level = HealthLevel.CRITICAL
            details = {"polling_active": True, "thread_alive": False}
        else:
            level = HealthLevel.HEALTHY
            details = {"polling_active": True, "thread_alive": True}

        return HealthResult(
            level=level, component=self.name, latency_ms=latency, details=details
        )


class SystemResourceChecker(BaseHealthChecker):
    """System resource checker."""

    def __init__(self, psutil_adapter) -> None:
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

            if memory_percent > 90 or cpu_percent > 95:
                level = HealthLevel.CRITICAL
            elif memory_percent > 80 or cpu_percent > 90:
                level = HealthLevel.UNHEALTHY
            elif memory_percent > 70 or cpu_percent > 80:
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
    def _parse_percentage(value: str | float) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str) and value.endswith("%"):
            try:
                return float(value[:-1])
            except ValueError:
                return 0.0
        return 0.0


class SessionChecker(BaseHealthChecker):
    """Session manager checker."""

    def __init__(self, session_manager) -> None:
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
            expired = stats.get("expired_sessions", 0)

            if total == 0:
                level = HealthLevel.HEALTHY
            else:
                blocked_ratio = blocked / total
                expired_ratio = expired / total

                if blocked_ratio > 0.5 or expired_ratio > 0.7:
                    level = HealthLevel.UNHEALTHY
                elif blocked_ratio > 0.3 or expired_ratio > 0.5:
                    level = HealthLevel.DEGRADED
                elif total > 1000:
                    level = HealthLevel.DEGRADED
                else:
                    level = HealthLevel.HEALTHY

            return HealthResult(
                level=level, component=self.name, latency_ms=latency, details=stats
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
        "_running",
        "_latest",
        "_intervals",
        "_base_interval",
        "_thread",
        "_stop_event",
    )

    def __init__(self, max_history: int = 15) -> None:
        super().__init__("health_monitor")
        self._checkers: dict[str, HealthChecker] = {}
        self._history: deque[SystemHealth] = deque(maxlen=max_history)
        self._max_history = max_history
        self._running = False
        self._latest: SystemHealth | None = None
        self._intervals: dict[str, float] = {}
        self._base_interval = 120.0
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    def add_checker(self, checker: HealthChecker) -> None:
        """Add health checker."""
        self._checkers[checker.name] = checker
        self._intervals[checker.name] = checker.interval_seconds

        with self.log_context(checker=checker.name) as log:
            log.debug(f"Added health checker: {checker.name}")

    def check_all(self) -> SystemHealth:
        """Perform health check on all components."""
        start_time = time.perf_counter()
        current_time = time.time()

        # Determine which components need checking
        to_check = []
        for name, checker in self._checkers.items():
            interval = self._intervals[name]
            last_check = 0.0

            if self._latest and name in self._latest.components:
                last_check = self._latest.components[name].timestamp

            if (current_time - last_check) >= interval:
                to_check.append((name, checker))

        # Use cached results if no checks needed
        if not to_check and self._latest:
            return self._latest

        # Start with previous results
        components = {}
        if self._latest:
            components.update(self._latest.components)

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
            if healthy_count >= len(levels) * 0.7:
                overall = max(overall, HealthLevel.DEGRADED)

        duration = (time.perf_counter() - start_time) * 1000

        health = SystemHealth(
            overall=overall,
            components=components,
            timestamp=current_time,
            check_duration_ms=duration,
        )

        self._history.append(health)
        self._latest = health

        return health

    def start_monitoring(self, base_interval: float = 120.0) -> None:
        """Start continuous monitoring in a separate thread."""
        if self._running:
            with self.log_context() as log:
                log.warning("Health monitoring already running")
            return

        self._base_interval = base_interval
        self._running = True
        self._stop_event.clear()

        self._thread = threading.Thread(
            target=self._monitor_loop, name="HealthMonitor", daemon=True
        )
        self._thread.start()

        with self.log_context(
            checkers=len(self._checkers), interval=base_interval
        ) as log:
            log.info("Health monitoring started")

    def stop_monitoring(self) -> None:
        """Stop monitoring."""
        if not self._running:
            return

        self._running = False
        self._stop_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)

        with self.log_context() as log:
            log.info("Health monitoring stopped")

    def _monitor_loop(self) -> None:
        """Main monitoring loop."""
        with self.log_context() as log:
            log.debug("Health monitoring loop started")

        while self._running and not self._stop_event.is_set():
            try:
                health = self.check_all()

                # Log based on health level
                log_methods = {
                    HealthLevel.HEALTHY: "debug",
                    HealthLevel.DEGRADED: "warning",
                    HealthLevel.UNHEALTHY: "warning",
                    HealthLevel.CRITICAL: "error",
                    HealthLevel.OFFLINE: "error",
                }

                log_method = log_methods.get(health.overall, "info")

                with self.log_context(
                    overall=str(health.overall),
                    operational=health.operational_count,
                    total=health.total_count,
                    health_ratio=f"{health.health_ratio:.1%}",
                    duration_ms=f"{health.check_duration_ms:.1f}",
                ) as log:
                    getattr(log, log_method)(f"Health: {health.overall}")

                # Adaptive interval
                if health.overall <= HealthLevel.UNHEALTHY:
                    interval = self._base_interval * 0.5
                elif health.overall == HealthLevel.DEGRADED:
                    interval = self._base_interval * 0.75
                else:
                    interval = self._base_interval

            except Exception as e:
                with self.log_context(error=str(e)) as log:
                    log.error("Health monitoring error")
                interval = self._base_interval

            # Sleep with early exit
            self._stop_event.wait(timeout=interval)

        with self.log_context() as log:
            log.debug("Health monitoring loop ended")

    @property
    def latest(self) -> SystemHealth | None:
        """Get latest health status."""
        return self._latest

    @property
    def is_healthy(self) -> bool:
        """Quick health check."""
        return self._latest is not None and self._latest.overall >= HealthLevel.DEGRADED

    def get_summary(self) -> dict[str, Any]:
        """Get health summary for logging."""
        if not self._latest:
            return {"status": "no_data"}

        return {
            "overall": str(self._latest.overall),
            "health_ratio": self._latest.health_ratio,
            "operational": self._latest.operational_count,
            "total": self._latest.total_count,
            "duration_ms": self._latest.check_duration_ms,
            "components": {
                name: {
                    "level": str(result.level),
                    "latency_ms": result.latency_ms,
                    "details": result.details,
                }
                for name, result in self._latest.components.items()
            },
        }


class HealthManager:
    """Simplified health manager that uses threading instead of asyncio."""

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
                log.error("Failed to start health monitoring")
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
                log.error("Failed to stop health monitoring")

    @property
    def is_healthy(self) -> bool:
        """Quick health check."""
        return self._monitor.is_healthy

    def get_summary(self) -> dict[str, Any]:
        """Get health summary."""
        return self._monitor.get_summary()

    @property
    def monitor(self):
        return self._monitor


# Factory functions
def create_health_monitor(
    bot: telebot.TeleBot, session_manager=None, psutil_adapter=None
) -> HealthMonitor:
    """Create configured health monitor."""
    monitor = HealthMonitor()

    bot_ref = ref(bot)
    monitor.add_checker(TelegramApiChecker(bot_ref))
    monitor.add_checker(PollingChecker(bot_ref))

    if session_manager:
        monitor.add_checker(SessionChecker(session_manager))

    if psutil_adapter:
        monitor.add_checker(SystemResourceChecker(psutil_adapter))

    try:
        from pytmbot.parsers.health_checker import TemplateParserChecker

        monitor.add_checker(TemplateParserChecker())
    except ImportError:
        pass  # Parser не доступен

    return monitor


def create_health_manager(
    bot: telebot.TeleBot, session_manager=None, psutil_adapter=None
) -> HealthManager:
    """Create configured health manager."""
    manager = HealthManager()

    bot_ref = ref(bot)
    manager.add_checker(TelegramApiChecker(bot_ref))
    manager.add_checker(PollingChecker(bot_ref))

    if session_manager:
        manager.add_checker(SessionChecker(session_manager))

    if psutil_adapter:
        manager.add_checker(SystemResourceChecker(psutil_adapter))

    try:
        from pytmbot.parsers.health_checker import TemplateParserChecker

        manager.add_checker(TemplateParserChecker())
    except ImportError:
        pass  # Parser не доступен

    return manager


# Legacy compatibility
class HealthStatus:
    """Legacy compatibility singleton."""

    _instance: HealthStatus | None = None
    _lock = threading.RLock()

    def __init__(self) -> None:
        self._manager: HealthManager | None = None
        self._lock = threading.RLock()

    def __new__(cls) -> HealthStatus:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def set_manager(self, manager: HealthManager) -> None:
        """Set health manager."""
        with self._lock:
            self._manager = manager

    @property
    def last_health_check_result(self) -> bool | None:
        """Legacy property."""
        with self._lock:
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
