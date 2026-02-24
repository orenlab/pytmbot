from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

import pytmbot.plugins.monitor.utils as monitor_utils_module
from pytmbot.plugins.monitor.models import MonitoringState
from pytmbot.plugins.monitor.utils import EventTracker, SystemInfo, SystemMetrics


@dataclass
class _TempEntry:
    current: float
    high: float | None
    critical: float | None
    label: str | None = None


@dataclass
class _FanEntry:
    current: int
    label: str | None = None


@dataclass
class _Partition:
    device: str
    mountpoint: str


@dataclass
class _Memory:
    percent: float


def test_collect_metrics_aggregates_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(SystemMetrics, "_check_cpu_usage", staticmethod(lambda: 11.0))
    monkeypatch.setattr(
        SystemMetrics, "_check_memory_usage", staticmethod(lambda: 22.0)
    )
    monkeypatch.setattr(
        SystemMetrics, "_get_disk_usage", staticmethod(lambda: {"/": 33.0})
    )
    monkeypatch.setattr(
        SystemMetrics, "_check_load_average", staticmethod(lambda: (1.0, 0.5, 0.2))
    )
    monkeypatch.setattr(
        SystemMetrics,
        "_check_temperatures",
        lambda self: {"cpu_pkg": {"current": 44.0, "high": 80.0, "critical": 90.0}},
    )
    monkeypatch.setattr(
        SystemMetrics,
        "_get_fan_speeds",
        staticmethod(lambda: {"fan_cpu": {"current": 900}}),
    )

    metrics = SystemMetrics().collect_metrics()
    assert metrics["cpu_usage"] == 11.0
    assert metrics["memory_usage"] == 22.0
    assert metrics["disk_usage"]["/"] == 33.0
    assert metrics["load_averages"] == (1.0, 0.5, 0.2)
    assert metrics["temperatures"]["cpu_pkg"]["current"] == 44.0
    assert metrics["fan_speeds"]["fan_cpu"]["current"] == 900


def test_cpu_and_memory_usage_fallback_on_invalid_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        monitor_utils_module,
        "psutil",
        SimpleNamespace(
            cpu_percent=lambda interval=1: "bad",
            virtual_memory=lambda: _Memory(percent="bad"),  # type: ignore[arg-type]
        ),
    )
    assert SystemMetrics._check_cpu_usage() == 0.0
    assert SystemMetrics._check_memory_usage() == 0.0


def test_cpu_and_memory_usage_fallback_on_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        monitor_utils_module,
        "psutil",
        SimpleNamespace(
            cpu_percent=lambda interval=1: (_ for _ in ()).throw(
                RuntimeError("cpu-fail")
            ),
            virtual_memory=lambda: (_ for _ in ()).throw(RuntimeError("mem-fail")),
        ),
    )
    assert SystemMetrics._check_cpu_usage() == 0.0
    assert SystemMetrics._check_memory_usage() == 0.0


def test_disk_usage_filters_excluded_and_handles_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        monitor_utils_module,
        "psutil",
        SimpleNamespace(
            disk_partitions=lambda all=False: [
                _Partition("/dev/sda1", "/"),
                _Partition("tmpfs", "/tmp"),
            ],
            disk_usage=lambda mountpoint: SimpleNamespace(
                percent=70.0 if mountpoint == "/" else 10.0
            ),
        ),
    )
    disk_usage = SystemMetrics._get_disk_usage()
    assert disk_usage == {"/dev/sda1": 70.0}

    monkeypatch.setattr(
        monitor_utils_module,
        "psutil",
        SimpleNamespace(
            disk_partitions=lambda all=False: (_ for _ in ()).throw(
                RuntimeError("disk-fail")
            ),
        ),
    )
    assert SystemMetrics._get_disk_usage() == {}


def test_temperature_and_fan_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    metrics = SystemMetrics()
    monkeypatch.setattr(
        monitor_utils_module,
        "psutil",
        SimpleNamespace(
            sensors_temperatures=lambda: {
                "cpu": [_TempEntry(current=55.0, high=80.0, critical=90.0, label="pkg")]
            },
            sensors_fans=lambda: {"fan": [_FanEntry(current=950, label="cpu")]},
        ),
    )
    temperatures = metrics._check_temperatures()
    fans = SystemMetrics._get_fan_speeds()
    assert temperatures["cpu_pkg"]["current"] == 55.0
    assert fans["fan_cpu"]["current"] == 950

    monkeypatch.setattr(
        monitor_utils_module,
        "psutil",
        SimpleNamespace(
            sensors_temperatures=lambda: {},
            sensors_fans=lambda: (_ for _ in ()).throw(RuntimeError("fan-fail")),
        ),
    )
    assert metrics._check_temperatures() == {}
    assert metrics.sensors_available is False
    assert metrics._check_temperatures() == {}
    assert SystemMetrics._get_fan_speeds() == {}


def test_load_average_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        monitor_utils_module,
        "psutil",
        SimpleNamespace(getloadavg=lambda: (1.0, 2.0, 3.0)),
    )
    assert SystemMetrics._check_load_average() == (1.0, 2.0, 3.0)

    monkeypatch.setattr(
        monitor_utils_module,
        "psutil",
        SimpleNamespace(getloadavg=lambda: ("bad", 2.0, 3.0)),
    )
    assert SystemMetrics._check_load_average() == (0.0, 0.0, 0.0)

    monkeypatch.setattr(
        monitor_utils_module,
        "psutil",
        SimpleNamespace(),
    )
    assert SystemMetrics._check_load_average() == (0.0, 0.0, 0.0)

    monkeypatch.setattr(
        monitor_utils_module,
        "psutil",
        SimpleNamespace(
            getloadavg=lambda: (_ for _ in ()).throw(RuntimeError("load-fail"))
        ),
    )
    assert SystemMetrics._check_load_average() == (0.0, 0.0, 0.0)


def test_event_tracker_create_and_resolve(monkeypatch: pytest.MonkeyPatch) -> None:
    state = MonitoringState()
    monkeypatch.setattr(monitor_utils_module, "uuid4", lambda: "event-id")
    timestamps = iter([100.0, 101.0, 140.0])
    monkeypatch.setattr(monitor_utils_module.time, "time", lambda: next(timestamps))

    event_id = EventTracker.create_event(state, "cpu", {"usage": 95.0})
    assert event_id == "event-id"
    assert state.active_events[event_id]["resolved"] is False

    duration = EventTracker.resolve_event(state, event_id)
    assert duration == 40.0
    assert state.active_events[event_id]["resolved"] is True
    assert EventTracker.resolve_event(state, event_id) is None
    assert EventTracker.resolve_event(state, "missing") is None


def test_system_info_metadata_success_and_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        monitor_utils_module.platform,
        "uname",
        lambda: SimpleNamespace(node="host-a", system="Linux", machine="x86_64"),
    )
    monkeypatch.setattr(
        monitor_utils_module.platform, "python_version", lambda: "3.12.0"
    )
    metadata = SystemInfo.get_platform_metadata(is_docker=True)
    assert metadata["system"] == "docker"
    assert metadata["hostname"] == "host-a"

    monkeypatch.setattr(
        monitor_utils_module.platform,
        "uname",
        lambda: (_ for _ in ()).throw(RuntimeError("uname-fail")),
    )
    fallback = SystemInfo.get_platform_metadata(is_docker=False)
    assert fallback == {"system": "unknown", "hostname": "unknown"}
