from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace, TracebackType
from typing import Literal, cast

import pytest
from telebot import TeleBot

import pytmbot.plugins.monitor.methods as monitor_methods_module
from pytmbot.adapters.psutil.adapter import PsutilAdapter
from pytmbot.adapters.psutil.adapter_types import CPUUsageStats, TopProcess
from pytmbot.db.influxdb_interface import InfluxDBInterface
from pytmbot.models.settings_model import (
    ChatIdModel,
    MonitorConfig,
    SettingsModel,
    TraceholdSettings,
)
from pytmbot.plugins.monitor.methods import SystemMonitorPlugin
from pytmbot.plugins.monitor.models import (
    MonitoringState,
    ResourceMetrics,
    ResourceThresholds,
)
from pytmbot.plugins.monitor.utils import SystemMetrics
from pytmbot.utils.environment import MetricScope, MetricScopes

type _PayloadScalar = str | int | float | bool | None
type _PayloadValue = _PayloadScalar | list["_PayloadValue"] | dict[str, "_PayloadValue"]
type _PayloadDict = dict[str, _PayloadValue]


@dataclass
class _BotStub:
    sent_messages: list[_PayloadDict] = field(default_factory=list)

    def send_message(
        self, chat_id: int, text: str, parse_mode: str | None = None
    ) -> None:
        self.sent_messages.append(
            {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        )


class _InfluxStub(InfluxDBInterface):
    __slots__ = ("write_result", "shutdown_wait_values", "close_calls")

    def __init__(self, write_result: bool = True) -> None:
        self.write_result = write_result
        self.shutdown_wait_values: list[bool] = []
        self.close_calls = 0

    def write_data_async(
        self,
        measurement: str,
        fields: dict[str, float],
        tags: dict[str, str] | None = None,
    ) -> bool:
        del measurement, fields, tags
        return self.write_result

    def shutdown_async_writes(self, *, wait: bool = True) -> None:
        self.shutdown_wait_values.append(wait)

    def connect(self) -> None:
        return None

    def close(self) -> None:
        self.close_calls += 1


class _PsutilStub(PsutilAdapter):
    __slots__ = ("cpu_percent", "top_processes", "raise_cpu", "raise_top")

    def __init__(
        self,
        *,
        cpu_percent: float = 10.0,
        top_processes: list[TopProcess] | None = None,
        raise_cpu: bool = False,
        raise_top: bool = False,
    ) -> None:
        self.cpu_percent = cpu_percent
        self.top_processes = top_processes or []
        self.raise_cpu = raise_cpu
        self.raise_top = raise_top

    def get_cpu_usage(self) -> CPUUsageStats:
        if self.raise_cpu:
            raise RuntimeError("boom")
        return {"cpu_percent": self.cpu_percent, "cpu_percent_per_core": []}

    def get_top_processes(self, count: int = 10) -> list[TopProcess]:
        del count
        if self.raise_top:
            raise RuntimeError("boom")
        return self.top_processes


class _SystemMetricsStub(SystemMetrics):
    __slots__ = ("_metrics",)

    def __init__(self, metrics: ResourceMetrics) -> None:
        super().__init__()
        self._metrics = metrics

    def collect_metrics(self, *, cpu_usage: float | None = None) -> ResourceMetrics:
        metrics = dict(self._metrics)
        if isinstance(cpu_usage, (int, float)):
            metrics["cpu_usage"] = float(cpu_usage)
        return cast(ResourceMetrics, metrics)


def _build_monitor(
    *,
    max_notifications: int = 2,
    reset_window_seconds: int = 300,
) -> tuple[SystemMonitorPlugin, _BotStub]:
    monitor = SystemMonitorPlugin.__new__(SystemMonitorPlugin)
    bot = _BotStub()
    monitor.bot = cast(TeleBot, bot)
    monitor.monitor_settings = MonitorConfig(
        tracehold=TraceholdSettings(
            cpu_usage_threshold=[80],
            memory_usage_threshold=[80],
            disk_usage_threshold=[80],
            cpu_temperature_threshold=[80],
            gpu_temperature_threshold=[80],
            disk_temperature_threshold=[80],
        ),
        max_notifications=[max_notifications],
        reset_notification_count=[reset_window_seconds],
        retry_interval=[1],
        retry_attempts=[2],
        check_interval=[5],
        monitor_docker=False,
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
    monitor.settings = SettingsModel.model_construct(
        chat_id=ChatIdModel(global_chat_id=[999]),
    )
    monitor.event_threshold_duration = 20.0
    monitor._previous_container_hashes = {}
    monitor._previous_image_hashes = {}
    monitor._previous_counts = {"containers_count": 0, "images_count": 0}
    monitor._known_container_ids = set()
    monitor._known_image_ids = set()
    monitor.influxdb_client = _InfluxStub()
    monitor.is_docker = True
    monitor._platform_metadata = {"system": "docker", "hostname": "test-host"}
    monitor.check_interval = 5
    monitor.docker_counters_update_interval = 300
    monitor._notification_reset_window_seconds = reset_window_seconds
    monitor._active_event_ids = {}
    monitor.system_metrics = _SystemMetricsStub(
        metrics={
            "cpu_usage": 10.0,
            "memory_usage": 20.0,
            "temperatures": {},
            "disk_usage": {},
            "fan_speeds": {},
            "load_averages": (0.1, 0.1, 0.1),
        }
    )
    monitor._monitor_thread = None
    monitor._supervisor_thread = None
    monitor._supervisor_stop_event = threading.Event()
    monitor._monitor_thread_lock = threading.RLock()
    monitor._monitor_restart_count = 0
    monitor._psutil_adapter = _PsutilStub()
    return monitor, bot


def test_send_notification_does_not_spawn_timer_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor, bot = _build_monitor(max_notifications=2, reset_window_seconds=300)
    monkeypatch.setattr("pytmbot.plugins.monitor.methods.time.time", lambda: 100.0)
    monkeypatch.setattr(
        "pytmbot.plugins.monitor.methods.threading.Timer",
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
    monkeypatch.setattr(
        "pytmbot.plugins.monitor.methods.time.time", lambda: next(timestamps)
    )

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
    monitor._supervisor_stop_event.set()

    class _DeadThread(threading.Thread):
        def __init__(self) -> None:
            super().__init__(daemon=True)

        def is_alive(self) -> bool:
            return False

    class _LiveThread(threading.Thread):
        def __init__(self) -> None:
            super().__init__(daemon=True)

        def is_alive(self) -> bool:
            return True

    monitor._monitor_thread = _DeadThread()

    def _spawn() -> threading.Thread:
        monitor.state.is_active = False
        return _LiveThread()

    monkeypatch.setattr(
        SystemMonitorPlugin,
        "_spawn_monitor_thread",
        lambda self: _spawn(),
    )

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
            "notified": True,
            "failed_attempts": 0,
        },
        "resolved": {
            "id": "resolved",
            "type": "cpu_usage",
            "resolved": True,
            "details": {},
            "start_time": 1.0,
            "last_notification": 1.0,
            "notified": True,
            "failed_attempts": 0,
        },
    }

    assert monitor._find_active_event_id("cpu_usage") == "active"
    assert monitor._find_active_event_id("memory_usage") is None

    notifications: list[str] = []

    def _send(
        self: SystemMonitorPlugin, text: str, *, log_failure: bool = True
    ) -> bool:
        del self, log_failure
        notifications.append(text)
        return True

    monkeypatch.setattr(SystemMonitorPlugin, "_send_notification", _send)
    monitor._create_or_notify_event(
        "cpu_usage", {"usage": 90.0}, lambda event_id: f"event:{event_id}"
    )
    assert notifications == []

    monkeypatch.setattr(
        "pytmbot.plugins.monitor.methods.EventTracker.create_event",
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
            "notified": True,
            "failed_attempts": 0,
        },
        "cpu-e2": {
            "id": "cpu-e2",
            "type": "cpu_usage",
            "resolved": True,
            "details": {},
            "start_time": 1.0,
            "last_notification": 1.0,
            "notified": True,
            "failed_attempts": 0,
        },
        "mem-e1": {
            "id": "mem-e1",
            "type": "memory_usage",
            "resolved": False,
            "details": {},
            "start_time": 1.0,
            "last_notification": 1.0,
            "notified": True,
            "failed_attempts": 0,
        },
    }
    monitor._active_event_ids = {}
    monkeypatch.setattr(
        "pytmbot.plugins.monitor.methods.EventTracker.resolve_event",
        lambda state, event_id: 12.5 if event_id == "cpu-e1" else None,
    )
    resolved: list[tuple[str, float]] = []
    monkeypatch.setattr(
        SystemMonitorPlugin,
        "_send_resolution_notification",
        lambda self, event_type, duration: resolved.append((event_type, duration)),
    )
    monitor._active_event_ids["cpu_usage"] = "cpu-e1"
    monitor._resolve_event_and_notify("cpu_usage", "CPU usage")
    assert resolved == [("CPU usage", 12.5)]
    assert "cpu-e1" not in monitor.state.active_events
    assert "cpu_usage" not in monitor._active_event_ids


def test_alert_checks_route_to_create_or_resolve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor, _bot = _build_monitor()
    monitor.thresholds.cpu_usage = 70.0
    monitor.thresholds.memory_usage = 60.0
    monitor.thresholds.disk_usage = 80.0

    created: list[tuple[str, _PayloadDict]] = []
    resolved: list[tuple[str, str]] = []
    monkeypatch.setattr(
        SystemMonitorPlugin,
        "_create_or_notify_event",
        lambda self, event_type, details, message_formatter, *message_args: (
            created.append((event_type, details))
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

    monkeypatch.setattr("pytmbot.plugins.monitor.methods.time.time", lambda: 100.0)
    monkeypatch.setattr(
        monitor_methods_module,
        "retrieve_containers_stats",
        lambda: [{"id": "c1", "name": "api", "status": "running"}],
    )
    monkeypatch.setattr(
        monitor_methods_module,
        "fetch_image_details",
        lambda: [{"id": "i1", "tags": ["latest"]}],
    )

    detected: list[tuple[dict[str, int], list[_PayloadDict], list[_PayloadDict]]] = []
    original_detect_changes = SystemMonitorPlugin._detect_docker_changes
    monkeypatch.setattr(
        SystemMonitorPlugin,
        "_detect_docker_changes",
        lambda self, counts, containers, images: detected.append(
            (counts, containers, images)
        ),
    )

    metrics: dict[str, object] = {}
    monitor._process_docker_metrics(metrics)
    assert monitor.state.docker_counters_last_updated == 100.0
    expected_docker_metrics = {
        "docker_containers_count": 1,
        "docker_images_count": 1,
        "docker_running_containers": 1,
        "docker_stopped_containers": 0,
    }
    assert {
        key: metrics[key] for key in expected_docker_metrics
    } == expected_docker_metrics
    assert detected
    monkeypatch.setattr(
        SystemMonitorPlugin,
        "_detect_docker_changes",
        original_detect_changes,
    )

    monitor.state.init_mode = True
    container_notifs: list[_PayloadDict] = []
    image_notifs: list[_PayloadDict] = []

    def _recorder(
        sink: list[_PayloadDict],
    ) -> Callable[[SystemMonitorPlugin, _PayloadDict], bool]:
        def _record(_self: SystemMonitorPlugin, details: _PayloadDict) -> bool:
            sink.append(details)
            return True

        return _record

    monkeypatch.setattr(
        SystemMonitorPlugin, "_send_container_notification", _recorder(container_notifs)
    )
    monkeypatch.setattr(
        SystemMonitorPlugin, "_send_image_notification", _recorder(image_notifs)
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

    class _CapturingInflux(_InfluxStub):
        __slots__ = ("writes",)

        def __init__(self) -> None:
            super().__init__(write_result=True)
            self.writes: list[tuple[str, dict[str, float], dict[str, str] | None]] = []

        def write_data_async(
            self,
            measurement: str,
            fields: dict[str, float],
            tags: dict[str, str] | None = None,
        ) -> bool:
            self.writes.append(
                (measurement, dict(fields), dict(tags) if tags else None)
            )
            return True

    influx_capture = _CapturingInflux()
    monitor.influxdb_client = influx_capture
    monkeypatch.setattr(
        "pytmbot.plugins.monitor.methods.SystemInfo.get_platform_metadata",
        staticmethod(lambda is_docker: {"system": "docker"}),
    )

    monitor._record_metrics(
        {"cpu": 10.0, "disk": {"root": 90.0, "label": "ignored"}, "flag": True}
    )
    assert influx_capture.writes
    measurement, fields, metadata = influx_capture.writes[-1]
    assert measurement == "system_metrics"
    assert fields["cpu"] == 10.0
    assert fields["disk_root"] == 90.0
    assert "disk_label" not in fields
    assert metadata is not None
    assert metadata["system"] == "docker"

    monitor.influxdb_client = _InfluxStub(write_result=False)
    monitor._record_metrics({"cpu": 20.0})


def _docker_scopes(processes: MetricScope) -> MetricScopes:
    return {
        "cpu": "host",
        "memory": "host",
        "processes": processes,
        "disks": "container",
        "disk_io": "host",
        "network": "unknown",
    }


@pytest.mark.parametrize(
    ("scopes", "expected_hint"),
    [
        (None, None),
        (_docker_scopes("host"), None),
        (
            _docker_scopes("container"),
            "<i>Processes: this container only (no pid: host).</i>",
        ),
        (
            _docker_scopes("unknown"),
            "<i>Processes: could not tell whether these are the host's or this "
            "container's.</i>",
        ),
    ],
)
def test_resource_alerts_flag_partial_process_lists(
    monkeypatch: pytest.MonkeyPatch,
    scopes: MetricScopes | None,
    expected_hint: str | None,
) -> None:
    monitor, _bot = _build_monitor()
    monkeypatch.setattr(SystemMonitorPlugin, "_get_top_processes", lambda self: [])
    monkeypatch.setattr(
        monitor_methods_module, "get_docker_metric_scopes", lambda: scopes
    )

    for text in (
        monitor._format_cpu_alert("ev-1", 95.0),
        monitor._format_memory_alert("ev-2", 88.0),
    ):
        last_line = text.splitlines()[-1]
        if expected_hint is None:
            assert "<i>" not in text
            assert last_line == "  • N/A"
        else:
            assert last_line == expected_hint


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

    hostile_process = monitor._format_process_info(
        [{"pid": 3, "name": "<x>", "cpu_percent": 99.0, "memory_percent": 1.0}],
        "cpu_percent",
    )
    assert "&lt;x&gt;" in hostile_process and "<x>" not in hostile_process
    assert "&lt;b" in SystemMonitorPlugin._format_disk_alert("ev-3", "/media/<b", 91.0)
    assert "a&amp;b" in SystemMonitorPlugin._format_temperature_alert(
        "ev-4", "a&b", {"current": 90.0}
    )

    messages: list[str] = []

    def _capture_notification(
        self: SystemMonitorPlugin, text: str, *, count_towards_budget: bool = True
    ) -> bool:
        del self, count_towards_budget
        messages.append(text)
        return True

    monkeypatch.setattr(
        SystemMonitorPlugin, "_send_notification", _capture_notification
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
    monitor._psutil_adapter = _PsutilStub(cpu_percent=75.0)
    monitor._adjust_check_interval()
    assert monitor.check_interval == 20

    monitor._psutil_adapter = _PsutilStub(cpu_percent=10.0)
    monitor._adjust_check_interval()
    assert monitor.check_interval == 5

    monitor._psutil_adapter = _PsutilStub(raise_cpu=True, raise_top=True)
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

    def _process_alerts(self: SystemMonitorPlugin, metrics: _PayloadDict) -> None:
        del self, metrics
        called.append("alerts")
        monitor.state.is_active = False

    monkeypatch.setattr(SystemMonitorPlugin, "_process_alerts", _process_alerts)
    monkeypatch.setattr(
        "pytmbot.plugins.monitor.methods.time.sleep", lambda seconds: None
    )
    monitor._monitor_system()
    # Resource alerts are evaluated before the (possibly slow) Docker refresh.
    assert called == ["adjust", "alerts", "docker", "record"]

    monitor.state.is_active = True
    monkeypatch.setattr(
        SystemMonitorPlugin,
        "_adjust_check_interval",
        lambda self: (_ for _ in ()).throw(RuntimeError("cycle-fail")),
    )
    monkeypatch.setattr(
        "pytmbot.plugins.monitor.methods.time.sleep",
        lambda seconds: setattr(monitor.state, "is_active", False),
    )
    monitor._monitor_system()

    class _ThreadStub(threading.Thread):
        def __init__(self) -> None:
            super().__init__(daemon=True)
            self.join_calls: list[float | None] = []

        def is_alive(self) -> bool:
            return True

        def join(self, timeout: float | None = None) -> None:
            self.join_calls.append(timeout)

    monitor.state.is_active = True
    monitor_thread = _ThreadStub()
    supervisor_thread = _ThreadStub()
    monitor._monitor_thread = monitor_thread
    monitor._supervisor_thread = supervisor_thread

    class _ShutdownInflux(_InfluxStub):
        __slots__ = ("calls", "close_called")

        def __init__(self) -> None:
            super().__init__()
            self.calls: list[bool] = []
            self.close_called = False

        def shutdown_async_writes(self, *, wait: bool = True) -> None:
            self.calls.append(wait)

        def close(self) -> None:
            self.close_called = True

    shutdown_capture = _ShutdownInflux()
    monitor.influxdb_client = shutdown_capture
    monkeypatch.setattr(
        "pytmbot.plugins.monitor.methods.threading.current_thread",
        threading.current_thread,
    )
    monitor.stop_monitoring()
    assert monitor.state.is_active is False
    assert monitor._monitor_thread is None
    assert monitor._supervisor_thread is None
    assert monitor_thread.join_calls == [monitor.MONITOR_THREAD_JOIN_TIMEOUT_SECONDS]
    assert supervisor_thread.join_calls == [monitor.MONITOR_THREAD_JOIN_TIMEOUT_SECONDS]
    assert shutdown_capture.calls == [True]
    assert shutdown_capture.close_called is True


def test_start_monitoring_happy_path_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor, _bot = _build_monitor()
    monitor.monitor_settings.retry_attempts = [2]
    monitor.monitor_settings.retry_interval = [1]
    monitor.state.is_active = False

    class _ThreadStub(threading.Thread):
        def __init__(self) -> None:
            super().__init__(daemon=True)
            self.started = False

        def start(self) -> None:
            self.started = True

    monkeypatch.setattr(
        SystemMonitorPlugin,
        "_spawn_monitor_thread",
        lambda self: _ThreadStub(),
    )
    monkeypatch.setattr(
        "pytmbot.plugins.monitor.methods.threading.Thread",
        lambda *args, **kwargs: _ThreadStub(),
    )

    class _LogCtx:
        def __enter__(self) -> SimpleNamespace:
            return SimpleNamespace(info=lambda *args, **kwargs: None)

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> Literal[False]:
            del exc_type, exc, tb
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
    monkeypatch.setattr(
        "pytmbot.plugins.monitor.methods.time.sleep", lambda seconds: None
    )
    with pytest.raises(
        RuntimeError, match="Failed to start monitoring after maximum attempts"
    ):
        failing_monitor.start_monitoring()
    assert failing_monitor.state.is_active is False


def _container_row(container_id: str) -> _PayloadDict:
    return {
        "id": container_id,
        "name": container_id,
        "image": "repo:tag",
        "status": "running",
        "networks": "bridge, backend",
        "ports": "0.0.0.0:8080->80/tcp",
    }


def test_undelivered_resource_alert_is_retried_and_not_recovered() -> None:
    monitor, bot = _build_monitor(max_notifications=5)
    telegram_up = [False]
    delivered = bot.send_message

    def _send(chat_id: int, text: str, parse_mode: str | None = None) -> None:
        if not telegram_up[0]:
            raise ConnectionError("telegram unavailable")
        delivered(chat_id, text, parse_mode)

    monitor.bot = cast(TeleBot, SimpleNamespace(send_message=_send))

    monitor._check_cpu_alert(95.0)
    event_id = monitor._find_active_event_id("cpu_usage")
    assert event_id is not None
    assert monitor.state.active_events[event_id]["notified"] is False

    telegram_up[0] = True
    monitor._check_cpu_alert(97.0)
    assert len(bot.sent_messages) == 1
    assert "High CPU Usage Alert" in str(bot.sent_messages[0]["text"])
    assert f"Event ID: {event_id}" in str(bot.sent_messages[0]["text"])

    monitor._check_cpu_alert(98.0)  # delivered: no repeat
    assert len(bot.sent_messages) == 1

    monitor._check_cpu_alert(10.0)
    assert "has normalized" in str(bot.sent_messages[-1]["text"])


def test_alert_delivery_logs_break_and_recovery_once_per_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor, bot = _build_monitor(max_notifications=5)
    records: list[tuple[str, str, dict[str, object]]] = []

    def _record(level: str) -> Callable[..., None]:
        def _log(message: str, *args: object, **kwargs: object) -> None:
            del args
            extra = kwargs.get("extra")
            records.append((level, message, extra if isinstance(extra, dict) else {}))

        return _log

    monkeypatch.setattr(
        monitor_methods_module,
        "logger",
        SimpleNamespace(
            **{level: _record(level) for level in ("debug", "info", "warning", "error")}
        ),
    )
    telegram_up = [False]
    delivered = bot.send_message

    def _send(chat_id: int, text: str, parse_mode: str | None = None) -> None:
        if not telegram_up[0]:
            raise ConnectionError("telegram unavailable")
        delivered(chat_id, text, parse_mode)

    monitor.bot = cast(TeleBot, SimpleNamespace(send_message=_send))

    for usage in (95.0, 96.0, 97.0):
        monitor._check_cpu_alert(usage)
    event_id = monitor._find_active_event_id("cpu_usage")
    telegram_up[0] = True
    monitor._check_cpu_alert(98.0)

    loud = [(level, message) for level, message, _ in records if level != "debug"]
    # Three failed cycles, then delivery: one error, one break, one recovery.
    assert loud == [
        ("error", "bot.plugins.monitor.methods.send.notification.fail"),
        ("warning", "bot.plugins.monitor.methods.alert.delivery.pending.warn"),
        ("info", "bot.plugins.monitor.methods.notification.sent.info"),
        ("info", "bot.plugins.monitor.methods.alert.delivery.restored.info"),
    ]
    traced = {
        message: extra for _, message, extra in records if ".alert.delivery." in message
    }
    assert traced["bot.plugins.monitor.methods.alert.delivery.pending.warn"] == {
        "event_id": event_id,
        "event_type": "cpu_usage",
    }
    restored = traced["bot.plugins.monitor.methods.alert.delivery.restored.info"]
    assert restored["event_id"] == event_id
    assert restored["failed_attempts"] == 3
    assert sum(level == "debug" for level, _, _ in records) == 2


def test_alert_resolved_before_delivery_is_logged_as_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor, bot = _build_monitor(max_notifications=1)
    monitor.state.notification_count = 1  # budget exhausted
    records: list[tuple[str, dict[str, object]]] = []

    def _info(message: str, *args: object, **kwargs: object) -> None:
        del args
        extra = kwargs.get("extra")
        records.append((message, extra if isinstance(extra, dict) else {}))

    monkeypatch.setattr(
        monitor_methods_module,
        "logger",
        SimpleNamespace(
            info=_info,
            warning=lambda *args, **kwargs: None,
            error=lambda *args, **kwargs: None,
            debug=lambda *args, **kwargs: None,
        ),
    )

    monitor._check_memory_alert(95.0)
    event_id = monitor._find_active_event_id("memory_usage")
    monitor._check_memory_alert(10.0)

    assert bot.sent_messages == []
    assert (
        "bot.plugins.monitor.methods.alert.delivery.dropped.info",
        {"event_id": event_id, "event_type": "memory_usage", "failed_attempts": 1},
    ) in records


def test_resource_alert_waits_for_notification_budget_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor, bot = _build_monitor(max_notifications=1, reset_window_seconds=60)
    clock = [1000.0]
    monkeypatch.setattr("pytmbot.plugins.monitor.methods.time.time", lambda: clock[0])

    monitor._check_cpu_alert(95.0)
    monitor._check_memory_alert(95.0)  # budget exhausted: not delivered
    assert len(bot.sent_messages) == 1

    clock[0] += 61
    monitor._check_memory_alert(96.0)
    assert len(bot.sent_messages) == 2
    assert "High Memory Usage Alert" in str(bot.sent_messages[-1]["text"])


def test_no_recovery_for_an_alert_that_was_never_delivered() -> None:
    monitor, bot = _build_monitor(max_notifications=1)
    monitor.state.notification_count = 1  # budget exhausted

    monitor._check_disk_alerts({"/": 95.0})
    monitor._check_disk_alerts({"/": 10.0})

    assert bot.sent_messages == []
    assert monitor._find_active_event_id("disk_/") is None


def test_security_alerts_bypass_exhausted_notification_budget() -> None:
    monitor, bot = _build_monitor(max_notifications=1)
    monitor.state.init_mode = False
    monitor.state.notification_count = 1  # resource-alert budget exhausted

    monitor._detect_docker_changes({}, [_container_row("c-new")], [])

    assert len(bot.sent_messages) == 1
    text = str(bot.sent_messages[0]["text"])
    assert "New Docker Container" in text
    assert "bridge, backend" in text and "0.0.0.0:8080-&gt;80/tcp" in text
    assert monitor._known_container_ids == {"c-new"}
    assert monitor.state.notification_count == 1


def test_failed_security_alert_is_retried_on_next_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor, bot = _build_monitor()
    monitor.state.init_mode = False
    send_results = iter([False, True])
    attempts: list[str] = []

    def _send(
        self: SystemMonitorPlugin, text: str, *, count_towards_budget: bool = True
    ) -> bool:
        del self, count_towards_budget
        attempts.append(text)
        return next(send_results)

    monkeypatch.setattr(SystemMonitorPlugin, "_send_notification", _send)

    monitor._detect_docker_changes({}, [_container_row("c-1")], [])
    assert monitor._known_container_ids == set()
    monitor._detect_docker_changes({}, [_container_row("c-1")], [])
    assert monitor._known_container_ids == {"c-1"}
    assert len(attempts) == 2
    assert bot.sent_messages == []


def test_security_alerts_are_queued_beyond_per_refresh_cap() -> None:
    monitor, bot = _build_monitor()
    monitor.state.init_mode = False
    rows = [_container_row(f"c-{index:02d}") for index in range(12)]

    monitor._detect_docker_changes({}, rows, [])
    assert len(bot.sent_messages) == SystemMonitorPlugin.MAX_SECURITY_ALERTS_PER_REFRESH
    monitor._detect_docker_changes({}, rows, [])
    assert len(bot.sent_messages) == 12
    assert len(monitor._known_container_ids) == 12


def test_known_ids_forget_removed_items() -> None:
    monitor, _bot = _build_monitor()
    monitor._detect_docker_changes(
        {}, [_container_row("c-1"), _container_row("c-2")], [{"id": "i-1"}]
    )
    assert monitor.state.init_mode is False
    monitor._detect_docker_changes({}, [_container_row("c-2")], [])
    assert monitor._known_container_ids == {"c-2"}
    assert monitor._known_image_ids == set()


def test_image_alert_shows_real_size() -> None:
    monitor, bot = _build_monitor()
    monitor.state.init_mode = False
    monitor._detect_docker_changes(
        {}, [], [{"id": "sha256:abc", "tags": ["app:1"], "size": "12.0 MiB"}]
    )
    text = str(bot.sent_messages[0]["text"])
    assert "12.0 MiB" in text
    assert "0 Bytes" not in text
    assert SystemMonitorPlugin._format_image_size(2048) == "2.0 KiB"
    assert SystemMonitorPlugin._format_image_size(None) == "unknown"


def test_docker_refresh_backs_off_after_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor, _bot = _build_monitor()
    monitor.docker_counters_update_interval = 300
    clock = [1000.0]
    calls: list[str] = []
    healthy = [False]

    def _containers() -> list[_PayloadDict]:
        calls.append("containers")
        if not healthy[0]:
            raise RuntimeError("docker unavailable")
        return [_container_row("c-1")]

    monkeypatch.setattr("pytmbot.plugins.monitor.methods.time.time", lambda: clock[0])
    monkeypatch.setattr(
        monitor_methods_module, "retrieve_containers_stats", _containers
    )
    monkeypatch.setattr(monitor_methods_module, "fetch_image_details", lambda: [])

    metrics: dict[str, object] = {}
    monitor._process_docker_metrics(metrics)
    assert monitor.state.docker_next_retry_at == 1030.0
    clock[0] += 5  # next monitor cycle: no Docker call inside the window
    monitor._process_docker_metrics(metrics)
    assert calls == ["containers"]

    clock[0] = 1030.0
    monitor._process_docker_metrics(metrics)
    assert monitor.state.docker_next_retry_at == 1090.0  # doubled
    assert len(calls) == 2

    healthy[0] = True
    clock[0] = 1090.0
    monitor._process_docker_metrics(metrics)
    assert monitor.state.docker_refresh_failures == 0
    assert monitor.state.docker_next_retry_at == 0.0
    assert metrics["docker_containers_count"] == 1

    monitor.state.docker_refresh_failures = 20
    assert monitor._schedule_docker_retry(0.0) == 300.0  # capped at the interval


def test_send_notification_reports_delivery(monkeypatch: pytest.MonkeyPatch) -> None:
    monitor, bot = _build_monitor(max_notifications=1)
    assert monitor._send_notification("a") is True
    assert monitor._send_notification("b") is False  # budget exhausted
    assert monitor._send_notification("c", count_towards_budget=False) is True

    def _broken_send(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("telegram down")

    monkeypatch.setattr(bot, "send_message", _broken_send)
    assert monitor._send_notification("d", count_towards_budget=False) is False
