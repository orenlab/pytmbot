from __future__ import annotations

import threading
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from weakref import ReferenceType, ref

import pytest
from telebot import TeleBot
from telebot.apihelper import ApiTelegramException

from pytmbot.health_system.health_system import (
    BaseHealthChecker,
    HealthLevel,
    HealthManager,
    HealthMonitor,
    HealthResult,
    HealthStatus,
    PollingChecker,
    SessionChecker,
    SystemHealth,
    SystemResourceChecker,
    TelegramApiChecker,
    create_health_manager,
    create_health_monitor,
)


class _StaticChecker(BaseHealthChecker):
    def __init__(
        self,
        name: str,
        result: HealthResult | None = None,
        *,
        raises: bool = False,
    ) -> None:
        super().__init__(cache_ttl=3600.0)
        self._name = name
        self._result = result
        self._raises = raises
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    def _perform_check(self) -> HealthResult:
        self.calls += 1
        if self._raises:
            raise RuntimeError("boom")
        if self._result is None:
            raise RuntimeError("no result")
        return self._result


@dataclass
class _FakeBotInfo:
    id: int
    username: str


class _FakeBot(TeleBot):
    def __init__(
        self, get_me_result: Any | None = None, raises: Exception | None = None
    ) -> None:
        super().__init__(token="12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE")
        self._get_me_result = get_me_result
        self._raises = raises
        self._TeleBot__polling_thread: object | None = None

    def get_me(self) -> Any:
        if self._raises is not None:
            raise self._raises
        return self._get_me_result


class _DeadThread:
    def is_alive(self) -> bool:
        return False


def _as_telebot_ref(bot: TeleBot) -> ReferenceType[TeleBot]:
    return ref(bot)


class _FakePsutilAdapter:
    def __init__(self, stats: dict[str, Any]):
        self._stats = stats

    def get_current_process_health_summary(self) -> dict[str, Any]:
        return self._stats


class _FakeSessionManager:
    def __init__(self, stats: dict[str, Any]):
        self._stats = stats

    def get_session_stats(self) -> dict[str, Any]:
        return self._stats


def test_health_result_and_system_health_properties() -> None:
    result = HealthResult(
        level=HealthLevel.DEGRADED,
        component="comp",
        latency_ms=10.0,
    )
    assert result.is_operational is True
    assert result.needs_attention is False

    system = SystemHealth(overall=HealthLevel.DEGRADED, components={"comp": result})
    assert system.operational_count == 1
    assert system.total_count == 1
    assert system.health_ratio == 0.0
    assert str(HealthLevel.HEALTHY) == "healthy"


def test_base_health_checker_uses_cache_and_handles_exceptions() -> None:
    healthy_result = HealthResult(
        level=HealthLevel.HEALTHY,
        component="cached",
        latency_ms=1.0,
    )
    checker = _StaticChecker("cached", healthy_result)
    assert checker.check_sync().level == HealthLevel.HEALTHY
    assert checker.check_sync().level == HealthLevel.HEALTHY
    assert checker.calls == 1

    failing = _StaticChecker("failing", raises=True)
    result = failing.check_sync()
    assert result.level == HealthLevel.CRITICAL
    assert result.details["error"] == "RuntimeError"


def test_telegram_api_checker_offline_when_bot_reference_is_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _FakeBot(get_me_result=_FakeBotInfo(id=1, username="bot"))
    bot_ref = _as_telebot_ref(bot)
    checker = TelegramApiChecker(bot_ref)
    monkeypatch.setattr(checker, "_bot_ref", lambda: None)
    result = checker._perform_check()
    assert result.level == HealthLevel.OFFLINE


def test_telegram_api_checker_success_and_api_error_paths() -> None:
    ok_bot = _FakeBot(get_me_result=_FakeBotInfo(1, "bot"))
    ok_checker = TelegramApiChecker(_as_telebot_ref(ok_bot))
    ok_result = ok_checker._perform_check()
    assert ok_result.level in {HealthLevel.HEALTHY, HealthLevel.DEGRADED}
    assert ok_result.details["bot_id"] == 1

    api_error = ApiTelegramException(
        "getMe",
        SimpleNamespace(status_code=403, text="forbidden"),
        {"error_code": 403, "description": "forbidden"},
    )
    fail_bot = _FakeBot(raises=api_error)
    fail_checker = TelegramApiChecker(_as_telebot_ref(fail_bot))
    fail_result = fail_checker._perform_check()
    assert fail_result.level == HealthLevel.CRITICAL
    assert fail_result.details["error_code"] == 403


def test_polling_checker_states() -> None:
    bot = _FakeBot(get_me_result=None)
    object.__setattr__(bot, "polling", False)
    checker = PollingChecker(_as_telebot_ref(bot))
    unhealthy = checker._perform_check()
    assert unhealthy.level == HealthLevel.UNHEALTHY

    object.__setattr__(bot, "polling", True)
    bot._TeleBot__polling_thread = _DeadThread()
    critical = checker._perform_check()
    assert critical.level == HealthLevel.CRITICAL

    bot._TeleBot__polling_thread = threading.current_thread()
    healthy = checker._perform_check()
    assert healthy.level == HealthLevel.HEALTHY


def test_system_resource_checker_thresholds() -> None:
    healthy_checker = SystemResourceChecker(
        _FakePsutilAdapter({"memory_percent": "50%", "cpu": "20%"})
    )
    assert healthy_checker._perform_check().level == HealthLevel.HEALTHY

    critical_checker = SystemResourceChecker(
        _FakePsutilAdapter({"memory_percent": "95%", "cpu": "10%"})
    )
    assert critical_checker._perform_check().level == HealthLevel.CRITICAL

    assert SystemResourceChecker._parse_percentage("42%") == 42.0
    assert SystemResourceChecker._parse_percentage("bad") == 0.0


def test_session_checker_levels() -> None:
    healthy = SessionChecker(
        _FakeSessionManager({"total_sessions": 0, "blocked_sessions": 0})
    )
    assert healthy._perform_check().level == HealthLevel.HEALTHY

    degraded = SessionChecker(
        _FakeSessionManager({"total_sessions": 10, "blocked_sessions": 4})
    )
    assert degraded._perform_check().level == HealthLevel.DEGRADED

    unhealthy = SessionChecker(
        _FakeSessionManager({"total_sessions": 10, "blocked_sessions": 8})
    )
    assert unhealthy._perform_check().level == HealthLevel.UNHEALTHY


def test_health_monitor_check_summary_and_lifecycle() -> None:
    monitor = HealthMonitor()
    monitor.add_checker(
        _StaticChecker(
            "a",
            HealthResult(level=HealthLevel.HEALTHY, component="a", latency_ms=1.0),
        )
    )
    monitor.add_checker(
        _StaticChecker(
            "b",
            HealthResult(level=HealthLevel.HEALTHY, component="b", latency_ms=1.0),
        )
    )
    monitor.add_checker(
        _StaticChecker(
            "c",
            HealthResult(level=HealthLevel.HEALTHY, component="c", latency_ms=1.0),
        )
    )
    monitor.add_checker(
        _StaticChecker(
            "d",
            HealthResult(level=HealthLevel.CRITICAL, component="d", latency_ms=1.0),
        )
    )
    system_health = monitor.check_all()
    assert system_health.overall == HealthLevel.DEGRADED
    summary = monitor.get_summary()
    assert summary["overall"] == "degraded"
    assert summary["total"] == 4

    monitor.start_monitoring(base_interval=0.01)
    monitor.stop_monitoring()


def test_health_manager_and_legacy_health_status() -> None:
    manager = HealthManager()
    monitor = manager.monitor
    monitor.add_checker(
        _StaticChecker(
            "ok",
            HealthResult(level=HealthLevel.HEALTHY, component="ok", latency_ms=1.0),
        )
    )
    manager.start(base_interval=0.01)
    manager.stop()

    legacy = HealthStatus()
    legacy.set_manager(manager)
    assert legacy.last_health_check_result in {True, False}
    legacy.last_health_check_result = True
    legacy.update_health(True)


def test_health_factory_functions_add_core_checkers() -> None:
    bot = _FakeBot(get_me_result=_FakeBotInfo(1, "bot"))
    session_manager = _FakeSessionManager({"total_sessions": 1, "blocked_sessions": 0})
    psutil_adapter = _FakePsutilAdapter({"memory_percent": "5%", "cpu": "2%"})

    monitor = create_health_monitor(bot, session_manager, psutil_adapter)
    summary = monitor.get_summary()
    assert summary == {"status": "no_data"}

    manager = create_health_manager(bot, session_manager, psutil_adapter)
    assert isinstance(manager.get_summary(), dict)
