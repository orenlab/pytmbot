from __future__ import annotations

import json
import os
import threading
import time
from collections.abc import Callable, Generator, Mapping
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import cast, override
from weakref import ReferenceType, ref

import pytest
from telebot import TeleBot
from telebot.apihelper import ApiTelegramException
from telebot.types import User

from pytmbot.health_system.health_system import (
    _TELEBOT_STOP_POLLING_ATTR,
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
)
from pytmbot.health_system.snapshot import (
    HealthSnapshot,
    HealthSnapshotWriter,
    ProbeStatus,
    evaluate_health_snapshot,
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


def _build_user(user_id: int, username: str | None = None) -> User:
    user_ctor = cast(Callable[..., User], User)
    return user_ctor(
        id=user_id,
        is_bot=True,
        first_name="pyTMBot",
        username=username,
    )


class _FakeBot(TeleBot):
    def __init__(
        self, get_me_result: User | None = None, raises: Exception | None = None
    ) -> None:
        super().__init__(token="12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE")
        self._get_me_result = get_me_result
        self._raises = raises

    def get_me(self) -> User:
        if self._raises is not None:
            raise self._raises
        if self._get_me_result is None:
            return _build_user(0, "unknown")
        return self._get_me_result


def _as_telebot_ref(bot: TeleBot) -> ReferenceType[TeleBot]:
    return ref(bot)


def _stop_polling(bot: TeleBot) -> None:
    stop_polling: Callable[[], object] = bot.stop_polling
    stop_polling()


class _FakePsutilAdapter:
    def __init__(self, stats: dict[str, object]):
        self._stats = stats

    def get_current_process_health_summary(self) -> dict[str, object]:
        return self._stats


class _FakeSessionManager:
    def __init__(self, stats: dict[str, int]):
        self._stats = stats

    def get_session_stats(self) -> dict[str, int]:
        return self._stats


def test_health_result_and_system_health_properties() -> None:
    result = HealthResult(
        level=HealthLevel.DEGRADED,
        component="comp",
        latency_ms=10.0,
    )
    assert result.is_operational is True

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
    bot = _FakeBot(get_me_result=_build_user(user_id=1, username="bot"))
    bot_ref = _as_telebot_ref(bot)
    checker = TelegramApiChecker(bot_ref)
    monkeypatch.setattr(checker, "_bot_ref", lambda: None)
    result = checker._perform_check()
    assert result.level == HealthLevel.OFFLINE


def test_telegram_api_checker_success_and_api_error_paths() -> None:
    ok_bot = _FakeBot(get_me_result=_build_user(user_id=1, username="bot"))
    ok_checker = TelegramApiChecker(_as_telebot_ref(ok_bot))
    ok_result = ok_checker._perform_check()
    assert ok_result.level in {HealthLevel.HEALTHY, HealthLevel.DEGRADED}
    assert ok_result.details["bot_id"] == 1

    api_error_ctor = cast(Callable[..., ApiTelegramException], ApiTelegramException)
    api_error = api_error_ctor(
        "getMe",
        SimpleNamespace(status_code=403, text="forbidden"),
        {"error_code": 403, "description": "forbidden"},
    )
    fail_bot = _FakeBot(raises=api_error)
    fail_checker = TelegramApiChecker(_as_telebot_ref(fail_bot))
    fail_result = fail_checker._perform_check()
    assert fail_result.level == HealthLevel.CRITICAL
    assert fail_result.details["error_code"] == 403


def test_telebot_still_exposes_the_stop_polling_event() -> None:
    # PollingChecker relies on this private TeleBot attribute; fail loudly on upgrade.
    bot = _FakeBot()
    assert isinstance(getattr(bot, _TELEBOT_STOP_POLLING_ATTR), threading.Event)
    # The public names the old checker used are not polling state.
    assert callable(bot.polling)
    assert not hasattr(bot, "polling_thread")


def test_polling_checker_follows_the_telebot_stop_event() -> None:
    bot = _FakeBot()
    checker = PollingChecker(_as_telebot_ref(bot))

    healthy = checker._perform_check()
    assert healthy.level == HealthLevel.HEALTHY
    assert healthy.details == {"polling_active": True}

    # Once stop_polling() is called, infinity_polling() no longer polls.
    _stop_polling(bot)
    stopped = checker._perform_check()
    assert stopped.level == HealthLevel.UNHEALTHY
    assert stopped.details == {"polling_active": False}


def test_polling_checker_degrades_when_state_is_unknown_or_bot_is_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _FakeBot()
    object.__setattr__(bot, _TELEBOT_STOP_POLLING_ATTR, None)
    checker = PollingChecker(_as_telebot_ref(bot))
    unknown = checker._perform_check()
    assert unknown.level == HealthLevel.DEGRADED
    assert unknown.details == {"error": "polling_state_unavailable"}

    monkeypatch.setattr(checker, "_bot_ref", lambda: None)
    assert checker._perform_check().level == HealthLevel.OFFLINE


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
    assert system_health.overall == HealthLevel.CRITICAL
    summary = monitor.get_summary()
    assert summary["overall"] == "critical"
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
    assert isinstance(legacy.get_summary(), dict)
    legacy.last_health_check_result = True


def test_health_factory_functions_add_core_checkers() -> None:
    bot = _FakeBot(get_me_result=_build_user(user_id=1, username="bot"))
    session_manager = _FakeSessionManager({"total_sessions": 1, "blocked_sessions": 0})
    psutil_adapter = _FakePsutilAdapter({"memory_percent": "5%", "cpu": "2%"})

    manager = create_health_manager(bot, session_manager, psutil_adapter)
    assert isinstance(manager.get_summary(), dict)


def _result(name: str, level: HealthLevel) -> HealthResult:
    return HealthResult(level=level, component=name, latency_ms=1.0)


class _SequenceChecker:
    """Uncached checker returning ``levels`` in order (the last one repeats)."""

    def __init__(
        self, name: str, levels: list[HealthLevel], interval: float = 3600.0
    ) -> None:
        self._name = name
        self._levels = levels
        self._interval = interval
        self.calls = 0

    @property
    def name(self) -> str:
        return self._name

    @property
    def interval_seconds(self) -> float:
        return self._interval

    def check_sync(self) -> HealthResult:
        level = self._levels[min(self.calls, len(self._levels) - 1)]
        self.calls += 1
        return _result(self._name, level)


class _RecordingWriter(HealthSnapshotWriter):
    def __init__(self, path: Path, *, fail: bool = False) -> None:
        super().__init__(path)
        self.fail = fail
        self.calls: list[dict[str, object]] = []
        self.written = threading.Event()

    @override
    def write(
        self,
        *,
        overall: str,
        healthy: bool,
        components: Mapping[str, str],
        interval_seconds: float,
    ) -> HealthSnapshot:
        self.calls.append(
            {
                "overall": overall,
                "healthy": healthy,
                "components": dict(components),
                "interval_seconds": interval_seconds,
            }
        )
        if self.fail:
            raise OSError(30, "Read-only file system")
        snapshot = super().write(
            overall=overall,
            healthy=healthy,
            components=components,
            interval_seconds=interval_seconds,
        )
        self.written.set()
        return snapshot


class _RecordingLog:
    def __init__(self, events: list[tuple[str, str]]) -> None:
        self._events = events

    def __getattr__(self, level: str) -> Callable[..., None]:
        def _record(event: str, *args: object, **kwargs: object) -> None:
            del args, kwargs
            self._events.append((level, event))

        return _record


def _capture_monitor_logs(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    events: list[tuple[str, str]] = []

    @contextmanager
    def _log_context(
        self: HealthMonitor, **kwargs: object
    ) -> Generator[_RecordingLog, None, None]:
        del self, kwargs
        yield _RecordingLog(events)

    monkeypatch.setattr(HealthMonitor, "log_context", _log_context)
    return events


def _wait_until(condition: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


def test_optional_components_can_only_degrade_the_overall_level() -> None:
    monitor = HealthMonitor()
    monitor.add_checker(_SequenceChecker("telegram_api", [HealthLevel.HEALTHY]))
    monitor.add_checker(
        _SequenceChecker("sessions", [HealthLevel.CRITICAL]), optional=True
    )
    monitor.add_checker(
        _SequenceChecker("system_resources", [HealthLevel.UNHEALTHY]), optional=True
    )

    health = monitor.check_all()

    assert health.overall == HealthLevel.DEGRADED
    assert health.components["sessions"].level == HealthLevel.CRITICAL
    assert monitor.is_healthy is True


def test_required_component_outage_is_not_softened_by_healthy_majority() -> None:
    # The removed heuristic turned UNHEALTHY into DEGRADED when >= 70% of the
    # components were up, which hid a Telegram API outage.
    monitor = HealthMonitor()
    monitor.add_checker(_SequenceChecker("telegram_api", [HealthLevel.UNHEALTHY]))
    for name in ("polling", "sessions", "system_resources", "template_parser"):
        monitor.add_checker(
            _SequenceChecker(name, [HealthLevel.HEALTHY]),
            optional=name != "polling",
        )

    assert monitor.check_all().overall == HealthLevel.UNHEALTHY
    assert monitor.is_healthy is False


def test_failing_component_is_rechecked_on_every_cycle() -> None:
    checker = _SequenceChecker(
        "telegram_api", [HealthLevel.UNHEALTHY, HealthLevel.HEALTHY]
    )
    monitor = HealthMonitor()
    monitor.add_checker(checker)

    assert monitor.check_all().overall == HealthLevel.UNHEALTHY
    # Not due for an hour, but failing: checked again and the recovery is seen.
    assert monitor.check_all().overall == HealthLevel.HEALTHY
    # Healthy and not due: the cached snapshot is reused.
    assert monitor.check_all().overall == HealthLevel.HEALTHY
    assert checker.calls == 2


def test_monitor_recovers_after_a_loop_failure() -> None:
    monitor = HealthMonitor()
    monitor.add_checker(_SequenceChecker("telegram_api", [HealthLevel.HEALTHY]))
    monitor.check_all()

    failed = monitor._publish_monitor_failure(RuntimeError("boom"))
    assert failed.overall == HealthLevel.CRITICAL
    assert set(failed.components) == {"telegram_api", "health_monitor"}

    recovered = monitor.check_all()
    assert set(recovered.components) == {"telegram_api"}
    assert recovered.overall == HealthLevel.HEALTHY
    assert monitor.is_healthy is True


def test_monitor_writes_snapshot_after_a_cycle_and_removes_it_on_stop(
    tmp_path: Path,
) -> None:
    snapshot_path = tmp_path / "health.json"
    writer = _RecordingWriter(snapshot_path)
    monitor = HealthMonitor(snapshot_writer=writer)
    monitor.add_checker(_SequenceChecker("telegram_api", [HealthLevel.HEALTHY]))
    monitor.add_checker(
        _SequenceChecker("sessions", [HealthLevel.UNHEALTHY]), optional=True
    )

    monitor.start_monitoring(base_interval=60.0)
    try:
        assert writer.written.wait(timeout=5.0)
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
        assert payload["pid"] == os.getpid()
        assert payload["overall"] == "degraded"
        assert payload["healthy"] is True
        assert payload["components"] == {
            "telegram_api": "healthy",
            "sessions": "unhealthy",
        }
        assert payload["stale_after"] - payload["timestamp"] == pytest.approx(180.0)
        assert evaluate_health_snapshot(snapshot_path).status is ProbeStatus.HEALTHY
    finally:
        monitor.stop_monitoring()

    assert not snapshot_path.exists()
    # A stopping monitor does not publish (and recreate the file) any more.
    monitor._publish_snapshot(monitor.check_all(), 60.0)
    assert not snapshot_path.exists()


def test_monitor_writes_unhealthy_snapshot_when_the_loop_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _broken_check_all(self: HealthMonitor) -> SystemHealth:
        del self
        raise RuntimeError("monitor loop broke")

    monkeypatch.setattr(HealthMonitor, "check_all", _broken_check_all)
    snapshot_path = tmp_path / "health.json"
    writer = _RecordingWriter(snapshot_path)
    monitor = HealthMonitor(snapshot_writer=writer)

    monitor.start_monitoring(base_interval=60.0)
    try:
        assert writer.written.wait(timeout=5.0)
        assert writer.calls[0]["healthy"] is False
        assert writer.calls[0]["components"] == {"health_monitor": "critical"}
        result = evaluate_health_snapshot(snapshot_path)
        assert result.status is ProbeStatus.UNHEALTHY
        assert "health_monitor=critical" in result.reason
    finally:
        monitor.stop_monitoring()


def test_snapshot_write_failures_are_logged_once_and_never_stop_monitoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events = _capture_monitor_logs(monkeypatch)
    writer = _RecordingWriter(tmp_path / "health.json", fail=True)
    monitor = HealthMonitor(snapshot_writer=writer)
    monitor.add_checker(_SequenceChecker("telegram_api", [HealthLevel.HEALTHY]))

    monitor.start_monitoring(base_interval=0.01)
    try:
        assert _wait_until(lambda: len(writer.calls) >= 3)
        thread = monitor._thread
        assert thread is not None
        assert thread.is_alive()
    finally:
        monitor.stop_monitoring()

    write_events = [event for event in events if "snapshot.write" in event[1]]
    assert write_events[0] == ("error", "bot.health.snapshot.write.fail")
    assert set(write_events[1:]) == {("debug", "bot.health.snapshot.write.retry.debug")}

    # The next successful write is reported once.
    monitor._stop_event.clear()
    writer.fail = False
    health = monitor.check_all()
    monitor._publish_snapshot(health, 60.0)
    monitor._publish_snapshot(health, 60.0)
    assert events.count(("info", "bot.health.snapshot.write.recovered")) == 1
    assert (tmp_path / "health.json").exists()


def _component_names(manager: HealthManager) -> set[str]:
    return set(manager.monitor.check_all().components)


def test_polling_mode_registers_the_polling_checker() -> None:
    manager = create_health_manager(
        _FakeBot(get_me_result=_build_user(user_id=1, username="bot")),
        _FakeSessionManager({"total_sessions": 1, "blocked_sessions": 0}),
        _FakePsutilAdapter({"memory_percent": "5%", "cpu": "2%"}),
    )

    assert _component_names(manager) == {
        "telegram_api",
        "polling",
        "sessions",
        "system_resources",
        "template_parser",
    }
    assert manager.monitor._optional == {
        "sessions",
        "system_resources",
        "template_parser",
    }
    assert manager.is_healthy is True


def test_webhook_mode_has_no_polling_checker_and_is_healthy() -> None:
    # Telegram pushes updates to the webhook server: there is no polling loop.
    manager = create_health_manager(
        _FakeBot(get_me_result=_build_user(user_id=1, username="bot")),
        _FakeSessionManager({"total_sessions": 1, "blocked_sessions": 0}),
        webhook_mode=True,
    )

    assert _component_names(manager) == {"telegram_api", "sessions", "template_parser"}
    assert manager.is_healthy is True


def test_minimal_setup_without_optional_providers() -> None:
    manager = create_health_manager(
        _FakeBot(get_me_result=_build_user(user_id=1, username="bot"))
    )

    assert _component_names(manager) == {"telegram_api", "polling", "template_parser"}
    assert manager.is_healthy is True


@pytest.mark.parametrize("webhook_mode", [False, True])
def test_telegram_api_outage_makes_the_bot_unhealthy_in_every_mode(
    webhook_mode: bool,
) -> None:
    manager = create_health_manager(
        _FakeBot(raises=ConnectionError("network is unreachable")),
        _FakeSessionManager({"total_sessions": 1, "blocked_sessions": 0}),
        _FakePsutilAdapter({"memory_percent": "5%", "cpu": "2%"}),
        webhook_mode=webhook_mode,
    )

    health = manager.monitor.check_all()

    assert health.components["telegram_api"].level == HealthLevel.UNHEALTHY
    assert health.overall == HealthLevel.UNHEALTHY
    assert manager.is_healthy is False


def test_stopped_polling_makes_the_bot_unhealthy_in_polling_mode() -> None:
    bot = _FakeBot(get_me_result=_build_user(user_id=1, username="bot"))
    manager = create_health_manager(bot)
    _stop_polling(bot)

    health = manager.monitor.check_all()

    assert health.components["polling"].level == HealthLevel.UNHEALTHY
    assert manager.is_healthy is False
