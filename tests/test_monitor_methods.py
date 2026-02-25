from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Literal, cast

import pytest
from telebot import TeleBot

import pytmbot.plugins.monitor.methods as monitor_methods_module
from pytmbot.plugins.monitor.methods import SystemMonitorPlugin
from pytmbot.plugins.monitor.models import MonitoringState, ResourceThresholds


@dataclass
class _BotStub:
    sent_messages: list[dict[str, object]] = field(default_factory=list)

    def send_message(
        self, chat_id: int, text: str, parse_mode: str | None = None
    ) -> None:
        self.sent_messages.append(
            {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        )


def _build_monitor(
    *,
    max_notifications: int = 2,
    reset_window_seconds: int = 300,
) -> tuple[SystemMonitorPlugin, _BotStub]:
    monitor = cast(SystemMonitorPlugin, object.__new__(SystemMonitorPlugin))
    bot = _BotStub()
    monitor.bot = cast(TeleBot, bot)
    monitor.monitor_settings = cast(
        Any,
        SimpleNamespace(
            max_notifications=[max_notifications],
            reset_notification_count=[reset_window_seconds],
            retry_interval=[1],
            retry_attempts=[2],
            check_interval=[5],
            monitor_docker=False,
            tracehold=SimpleNamespace(),
        ),
    )
    monitor.state = MonitoringState()
    monitor.thresholds = ResourceThresholds(
        cpu_temp=80.0,
        gpu_temp=80.0,
        disk_temp=80.0,
        pch_temp=80.0,
        cpu_usage=80.0,
        memory_usage=80.0,
        disk_usage=80.0,
        load=70.0,
    )
    monitor.settings = cast(
        Any, SimpleNamespace(chat_id=SimpleNamespace(global_chat_id=[999]))
    )
    monitor.event_threshold_duration = 20.0
    monitor._previous_container_hashes = {}
    monitor._previous_image_hashes = {}
    monitor._previous_counts = {"containers_count": 0, "images_count": 0}
    monitor._known_container_ids = set()
    monitor._known_image_ids = set()
    monitor.influxdb_client = cast(
        Any,
        SimpleNamespace(
            write_data_async=lambda measurement, fields, tags: True,
            shutdown_async_writes=lambda wait: None,
        ),
    )
    monitor.is_docker = True
    monitor.check_interval = 5
    monitor.docker_counters_update_interval = 300
    monitor.system_metrics = cast(
        Any,
        SimpleNamespace(
            collect_metrics=lambda: {
                "cpu_usage": 10.0,
                "memory_usage": 20.0,
                "temperatures": {},
                "disk_usage": {},
            }
        ),
    )
    monitor._monitor_thread = None
    monitor._supervisor_thread = None
    monitor._monitor_thread_lock = monitor_methods_module.threading.RLock()
    monitor._monitor_restart_count = 0
    monitor._psutil_adapter = cast(
        Any,
        SimpleNamespace(
            get_top_processes=lambda count=5: [],
            get_cpu_usage=lambda: {"cpu_percent": 10.0},
        ),
    )
    return monitor, bot


def test_send_notification_does_not_spawn_timer_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor, bot = _build_monitor(max_notifications=2, reset_window_seconds=300)
    monkeypatch.setattr(monitor_methods_module.time, "time", lambda: 100.0)
    monkeypatch.setattr(
        monitor_methods_module.threading,
        "Timer",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Timer must not be used")
        ),
    )

    monitor._send_notification("alert-1")
    monitor._send_notification("alert-2")
    monitor._send_notification("alert-3")

    assert len(bot.sent_messages) == 2
    assert monitor.state.notification_count == 2
    assert monitor.state.max_notifications_reached is True
    assert monitor.state.next_notification_reset_at == 400.0


def test_send_notification_resets_budget_lazily_after_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor, bot = _build_monitor(max_notifications=2, reset_window_seconds=300)
    timestamps = iter([100.0, 101.0, 500.0])
    monkeypatch.setattr(monitor_methods_module.time, "time", lambda: next(timestamps))

    monitor._send_notification("alert-1")
    monitor._send_notification("alert-2")
    monitor._send_notification("alert-3")

    assert len(bot.sent_messages) == 3
    assert monitor.state.notification_count == 1
    assert monitor.state.max_notifications_reached is False
    assert monitor.state.next_notification_reset_at == 800.0


def test_supervisor_restarts_dead_monitor_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor, _bot = _build_monitor(max_notifications=2, reset_window_seconds=300)
    monitor.state.is_active = True

    class _DeadThread:
        @staticmethod
        def is_alive() -> bool:
            return False

    class _LiveThread:
        @staticmethod
        def is_alive() -> bool:
            return True

    monitor._monitor_thread = cast(Any, _DeadThread())

    def _spawn() -> _LiveThread:
        monitor.state.is_active = False
        return _LiveThread()

    monkeypatch.setattr(
        SystemMonitorPlugin,
        "_spawn_monitor_thread",
        lambda self: _spawn(),
    )
    monkeypatch.setattr(monitor_methods_module.time, "sleep", lambda _seconds: None)

    monitor._supervise_monitoring()

    assert isinstance(monitor._monitor_thread, _LiveThread)
    assert monitor._monitor_restart_count == 1


def test_sanitize_fields_flattens_nested_values() -> None:
    fields = {
        "cpu": 20.0,
        "meta": "ok",
        "disk": {"root": 80.0, "note": "skip"},
        "load": (0.5, 0.4, 0.3, "skip"),
        "unsupported": ["x"],
    }

    sanitized = SystemMonitorPlugin._sanitize_fields(fields)
    assert sanitized["cpu"] == 20.0
    assert sanitized["meta"] == "ok"
    assert sanitized["disk_root"] == 80.0
    assert sanitized["load_1m"] == 0.5
    assert sanitized["load_2m"] == 0.4
    assert sanitized["load_3m"] == 0.3
    assert "unsupported" not in sanitized
    assert "disk_note" not in sanitized


def test_event_helpers_create_find_and_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    monitor, _bot = _build_monitor()
    monitor.state.active_events = {
        "active": {
            "id": "active",
            "type": "cpu_usage",
            "resolved": False,
            "details": {},
            "start_time": 1.0,
            "last_notification": 1.0,
        },
        "resolved": {
            "id": "resolved",
            "type": "cpu_usage",
            "resolved": True,
            "details": {},
            "start_time": 1.0,
            "last_notification": 1.0,
        },
    }

    assert monitor._find_active_event_id("cpu_usage") == "active"
    assert monitor._find_active_event_id("memory_usage") is None

    notifications: list[str] = []
    monkeypatch.setattr(
        SystemMonitorPlugin,
        "_send_notification",
        lambda self, text: notifications.append(text),
    )
    monitor._create_or_notify_event(
        "cpu_usage", {"usage": 90.0}, lambda event_id: f"event:{event_id}"
    )
    assert notifications == []

    monkeypatch.setattr(
        monitor_methods_module.EventTracker,
        "create_event",
        lambda state, event_type, details: "new-event",
    )
    monitor._create_or_notify_event(
        "memory_usage", {"usage": 91.0}, lambda event_id: f"event:{event_id}"
    )
    assert notifications[-1] == "event:new-event"

    monitor.state.active_events = {
        "cpu-e1": {
            "id": "cpu-e1",
            "type": "cpu_usage",
            "resolved": False,
            "details": {},
            "start_time": 1.0,
            "last_notification": 1.0,
        },
        "cpu-e2": {
            "id": "cpu-e2",
            "type": "cpu_usage",
            "resolved": True,
            "details": {},
            "start_time": 1.0,
            "last_notification": 1.0,
        },
        "mem-e1": {
            "id": "mem-e1",
            "type": "memory_usage",
            "resolved": False,
            "details": {},
            "start_time": 1.0,
            "last_notification": 1.0,
        },
    }
    monkeypatch.setattr(
        monitor_methods_module.EventTracker,
        "resolve_event",
        lambda state, event_id: 12.5 if event_id == "cpu-e1" else None,
    )
    resolved: list[tuple[str, float]] = []
    monkeypatch.setattr(
        SystemMonitorPlugin,
        "_send_resolution_notification",
        lambda self, event_type, duration: resolved.append((event_type, duration)),
    )
    monitor._resolve_event_and_notify("cpu_usage", "CPU usage")
    assert resolved == [("CPU usage", 12.5)]


def test_alert_checks_route_to_create_or_resolve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor, _bot = _build_monitor()
    monitor.thresholds.cpu_usage = 70.0
    monitor.thresholds.memory_usage = 60.0
    monitor.thresholds.disk_usage = 80.0

    created: list[tuple[str, dict[str, Any]]] = []
    resolved: list[tuple[str, str]] = []
    monkeypatch.setattr(
        SystemMonitorPlugin,
        "_create_or_notify_event",
        lambda self, event_type, details, message_builder: created.append(
            (event_type, details)
        ),
    )
    monkeypatch.setattr(
        SystemMonitorPlugin,
        "_resolve_event_and_notify",
        lambda self, event_type, label: resolved.append((event_type, label)),
    )

    monitor._check_cpu_alert(71.0)
    monitor._check_cpu_alert(10.0)
    monitor._check_memory_alert(61.0)
    monitor._check_memory_alert(20.0)
    monitor._check_temperature_alerts(
        {"cpu": {"current": 90.0}, "gpu": {"current": 40.0}}
    )
    monitor._check_disk_alerts({"sda": 95.0, "sdb": 10.0})

    assert ("cpu_usage", {"usage": 71.0}) in created
    assert ("memory_usage", {"usage": 61.0}) in created
    assert ("temp_cpu", {"temperature": 90.0, "sensor": "cpu"}) in created
    assert ("disk_sda", {"usage": 95.0, "disk": "sda"}) in created
    assert ("cpu_usage", "CPU usage") in resolved
    assert ("memory_usage", "Memory usage") in resolved
    assert ("temp_gpu", "Temperature (gpu)") in resolved
    assert ("disk_sdb", "Disk usage (sdb)") in resolved


def test_process_docker_metrics_and_detect_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor, _bot = _build_monitor()
    monitor.state.docker_counters_last_updated = 0.0
    monitor.docker_counters_update_interval = 10

    monkeypatch.setattr(monitor_methods_module.time, "time", lambda: 100.0)
    monkeypatch.setattr(
        monitor_methods_module,
        "fetch_docker_counters",
        lambda: {"containers_count": 2, "images_count": 3},
    )
    monkeypatch.setattr(
        monitor_methods_module,
        "retrieve_containers_stats",
        lambda: [{"id": "c1", "name": "api"}],
    )
    monkeypatch.setattr(
        monitor_methods_module,
        "fetch_image_details",
        lambda: [{"id": "i1", "tags": ["latest"]}],
    )

    detected: list[
        tuple[dict[str, int], list[dict[str, Any]], list[dict[str, Any]]]
    ] = []
    original_detect_changes = SystemMonitorPlugin._detect_docker_changes
    monkeypatch.setattr(
        SystemMonitorPlugin,
        "_detect_docker_changes",
        lambda self, counts, containers, images: detected.append(
            (counts, containers, images)
        ),
    )

    metrics: dict[str, Any] = {}
    monitor._process_docker_metrics(metrics)
    assert monitor.state.docker_counters_last_updated == 100.0
    assert metrics["docker_containers_count"] == 2
    assert metrics["docker_images_count"] == 3
    assert detected
    monkeypatch.setattr(
        SystemMonitorPlugin,
        "_detect_docker_changes",
        original_detect_changes,
    )

    monitor.state.init_mode = True
    container_notifs: list[dict[str, Any]] = []
    image_notifs: list[dict[str, Any]] = []
    monkeypatch.setattr(
        SystemMonitorPlugin,
        "_send_container_notification",
        lambda self, details: container_notifs.append(details),
    )
    monkeypatch.setattr(
        SystemMonitorPlugin,
        "_send_image_notification",
        lambda self, details: image_notifs.append(details),
    )
    monitor._detect_docker_changes(
        {"containers_count": 1, "images_count": 1},
        [{"id": "c1", "name": "api"}],
        [{"id": "i1", "tags": ["latest"]}],
    )
    assert monitor.state.init_mode is False
    assert container_notifs == []
    assert image_notifs == []

    monitor._detect_docker_changes(
        {"containers_count": 2, "images_count": 2},
        [{"id": "c1", "name": "api"}, {"id": "c2", "name": "worker"}],
        [{"id": "i1", "tags": ["latest"]}, {"id": "i2", "tags": ["1.0"]}],
    )
    assert container_notifs and container_notifs[-1]["id"] == "c2"
    assert image_notifs and image_notifs[-1]["id"] == "i2"


def test_record_metrics_writes_sanitized_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monitor, _bot = _build_monitor()
    writes: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    def _write_data_async(
        measurement: str,
        fields: dict[str, Any],
        metadata: dict[str, Any],
    ) -> bool:
        writes.append((measurement, fields, metadata))
        return True

    monitor.influxdb_client = cast(
        Any,
        SimpleNamespace(write_data_async=_write_data_async),
    )
    monkeypatch.setattr(
        monitor_methods_module.SystemInfo,
        "get_platform_metadata",
        staticmethod(lambda is_docker: {"system": "docker"}),
    )

    monitor._record_metrics(
        {"cpu": 10.0, "disk": {"root": 90.0, "label": "ignored"}, "flag": True}
    )
    assert writes
    measurement, fields, metadata = writes[-1]
    assert measurement == "system_metrics"
    assert fields["cpu"] == 10.0
    assert fields["disk_root"] == 90.0
    assert "disk_label" not in fields
    assert metadata["system"] == "docker"

    monitor.influxdb_client = cast(
        Any,
        SimpleNamespace(write_data_async=lambda measurement, fields, metadata: False),
    )
    monitor._record_metrics({"cpu": 20.0})


def test_alert_formatting_and_notifications(monkeypatch: pytest.MonkeyPatch) -> None:
    monitor, _bot = _build_monitor()
    monkeypatch.setattr(
        SystemMonitorPlugin,
        "_get_top_processes",
        lambda self: [
            {"pid": 7, "name": "python", "cpu_percent": 55.0, "memory_percent": 12.0}
        ],
    )
    cpu_text = monitor._format_cpu_alert("ev-1", 95.0)
    mem_text = monitor._format_memory_alert("ev-2", 88.0)
    assert "ev-1" in cpu_text and "python" in cpu_text
    assert "ev-2" in mem_text and "% MEM" in mem_text

    assert "N/A" in monitor._format_process_info([], "cpu_percent")
    process_info = monitor._format_process_info(
        [
            {"pid": 1, "name": "a", "cpu_percent": 10.0, "memory_percent": 2.0},
            {"pid": 2, "name": "b", "cpu_percent": 20.0, "memory_percent": 1.0},
        ],
        "cpu_percent",
    )
    assert process_info.splitlines()[0].startswith("  • b")

    messages: list[str] = []
    monkeypatch.setattr(
        SystemMonitorPlugin,
        "_send_notification",
        lambda self, text: messages.append(text),
    )
    monkeypatch.setattr(
        monitor_methods_module, "set_naturalsize", lambda value: "2 MiB"
    )
    monitor._send_container_notification(
        {
            "name": "api",
            "image": "repo:tag",
            "created": "now",
            "run_at": "now",
            "status": "running",
            "networks": "bridge",
            "ports": "80/tcp",
        }
    )
    monitor._send_image_notification(
        {
            "id": "sha256:1234567890abcdef",
            "tags": ["latest"],
            "architecture": "amd64",
            "os": "linux",
            "size": 1024,
            "created": "today",
        }
    )
    monitor._send_resolution_notification("CPU usage", 42.0)
    assert "New Docker Container" in messages[0]
    assert "2 MiB" in messages[1]
    assert "Duration: 42 seconds" in messages[2]


def test_adjust_interval_and_top_process_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor, _bot = _build_monitor()
    monitor.check_interval = 10
    monitor.thresholds.load = 50.0
    monitor.monitor_settings.check_interval = [5]
    monitor._psutil_adapter = cast(
        Any, SimpleNamespace(get_cpu_usage=lambda: {"cpu_percent": 75.0})
    )
    monitor._adjust_check_interval()
    assert monitor.check_interval == 20

    monitor._psutil_adapter = cast(
        Any, SimpleNamespace(get_cpu_usage=lambda: {"cpu_percent": 10.0})
    )
    monitor._adjust_check_interval()
    assert monitor.check_interval == 5

    monitor._psutil_adapter = cast(
        Any,
        SimpleNamespace(
            get_cpu_usage=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
            get_top_processes=lambda count=5: (_ for _ in ()).throw(
                RuntimeError("boom")
            ),
        ),
    )
    monitor._adjust_check_interval()
    assert monitor._get_top_processes() == []


def test_monitor_cycle_and_stop_monitoring(monkeypatch: pytest.MonkeyPatch) -> None:
    monitor, _bot = _build_monitor()
    monitor.state.is_active = True
    monitor.monitor_settings.monitor_docker = True
    monitor.check_interval = 4
    called: list[str] = []
    monkeypatch.setattr(
        SystemMonitorPlugin,
        "_adjust_check_interval",
        lambda self: called.append("adjust"),
    )
    monkeypatch.setattr(
        SystemMonitorPlugin,
        "_process_docker_metrics",
        lambda self, metrics: called.append("docker"),
    )
    monkeypatch.setattr(
        SystemMonitorPlugin,
        "_record_metrics",
        lambda self, metrics: called.append("record"),
    )

    def _process_alerts(self: SystemMonitorPlugin, metrics: dict[str, Any]) -> None:
        del self, metrics
        called.append("alerts")
        monitor.state.is_active = False

    monkeypatch.setattr(SystemMonitorPlugin, "_process_alerts", _process_alerts)
    monkeypatch.setattr(monitor_methods_module.time, "sleep", lambda seconds: None)
    monitor._monitor_system()
    assert called == ["adjust", "docker", "record", "alerts"]

    monitor.state.is_active = True
    monkeypatch.setattr(
        SystemMonitorPlugin,
        "_adjust_check_interval",
        lambda self: (_ for _ in ()).throw(RuntimeError("cycle-fail")),
    )
    monkeypatch.setattr(
        monitor_methods_module.time,
        "sleep",
        lambda seconds: setattr(monitor.state, "is_active", False),
    )
    monitor._monitor_system()

    class _ThreadStub:
        def __init__(self) -> None:
            self.join_calls: list[float | None] = []

        def is_alive(self) -> bool:
            return True

        def join(self, timeout: float | None = None) -> None:
            self.join_calls.append(timeout)

    monitor.state.is_active = True
    monitor_thread = _ThreadStub()
    supervisor_thread = _ThreadStub()
    monitor._monitor_thread = cast(Any, monitor_thread)
    monitor._supervisor_thread = cast(Any, supervisor_thread)
    shutdown_calls: list[bool] = []
    monitor.influxdb_client = cast(
        Any,
        SimpleNamespace(shutdown_async_writes=lambda wait: shutdown_calls.append(wait)),
    )
    monkeypatch.setattr(
        monitor_methods_module.threading,
        "current_thread",
        lambda: cast(Any, object()),
    )
    monitor.stop_monitoring()
    assert monitor.state.is_active is False
    assert monitor._monitor_thread is None
    assert monitor._supervisor_thread is None
    assert monitor_thread.join_calls == [monitor.MONITOR_THREAD_JOIN_TIMEOUT_SECONDS]
    assert supervisor_thread.join_calls == [monitor.MONITOR_THREAD_JOIN_TIMEOUT_SECONDS]
    assert shutdown_calls == [True]


def test_start_monitoring_happy_path_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor, _bot = _build_monitor()
    monitor.monitor_settings.retry_attempts = [2]
    monitor.monitor_settings.retry_interval = [1]
    monitor.state.is_active = False

    class _ThreadStub:
        def __init__(self) -> None:
            self.started = False

        def start(self) -> None:
            self.started = True

    monkeypatch.setattr(
        SystemMonitorPlugin,
        "_spawn_monitor_thread",
        lambda self: cast(Any, _ThreadStub()),
    )
    monkeypatch.setattr(
        monitor_methods_module.threading,
        "Thread",
        lambda *args, **kwargs: _ThreadStub(),
    )

    class _LogCtx:
        def __enter__(self) -> Any:
            return SimpleNamespace(info=lambda *args, **kwargs: None)

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> Literal[False]:
            return False

    logger_stub = SimpleNamespace(
        context=lambda context: _LogCtx(),
        error=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        debug=lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(monitor_methods_module, "logger", logger_stub)
    monitor.start_monitoring()
    assert monitor.state.is_active is True
    assert monitor._monitor_thread is not None
    assert monitor._supervisor_thread is not None

    failing_monitor, _bot2 = _build_monitor()
    failing_monitor.monitor_settings.retry_attempts = [2]
    failing_monitor.monitor_settings.retry_interval = [1]
    monkeypatch.setattr(
        SystemMonitorPlugin,
        "_spawn_monitor_thread",
        lambda self: (_ for _ in ()).throw(RuntimeError("spawn fail")),
    )
    monkeypatch.setattr(monitor_methods_module.time, "sleep", lambda seconds: None)
    with pytest.raises(
        RuntimeError, match="Failed to start monitoring after maximum attempts"
    ):
        failing_monitor.start_monitoring()
    assert failing_monitor.state.is_active is False
