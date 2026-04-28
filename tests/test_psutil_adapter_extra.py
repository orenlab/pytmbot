from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass
from types import SimpleNamespace
from typing import cast

import psutil
import pytest

import pytmbot.adapters.psutil.adapter as psutil_adapter_module


@dataclass
class _FakeCpuTimes:
    user: float = 1.0
    system: float = 2.0

    def _asdict(self) -> dict[str, float]:
        return {"user": self.user, "system": self.system}


@dataclass
class _FakeIoCounters:
    read_count: int = 1
    write_count: int = 2
    read_bytes: int = 1024
    write_bytes: int = 2048
    read_chars: int = 3
    write_chars: int = 4


@dataclass
class _FakeCtxSwitches:
    voluntary: int = 5
    involuntary: int = 6


@dataclass
class _FakeMemoryInfo:
    rss: int = 1000
    vms: int = 2000


def _new_adapter_without_warmup(
    monkeypatch: pytest.MonkeyPatch,
) -> psutil_adapter_module.PsutilAdapter:
    monkeypatch.setattr(
        psutil_adapter_module.PsutilAdapter, "_start_cpu_warmup", lambda self: None
    )
    return psutil_adapter_module.PsutilAdapter()


def _clear_cached_method(method: object) -> None:
    cache_clear = getattr(method, "cache_clear", None)
    if callable(cache_clear):
        cache_clear()


def test_thread_safe_cache_respects_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [100.0]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    calls = {"count": 0}

    @psutil_adapter_module.thread_safe_cache(maxsize=2, ttl_seconds=1.0)
    def _expensive(value: int) -> int:
        calls["count"] += 1
        return value * 2

    assert _expensive(3) == 6
    assert _expensive(3) == 6
    assert calls["count"] == 1

    clock[0] = 102.0
    assert _expensive(3) == 6
    assert calls["count"] == 2


def test_thread_safe_cache_eviction_when_full(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [100.0]
    monkeypatch.setattr(time, "time", lambda: clock[0])
    calls = {"count": 0}

    @psutil_adapter_module.thread_safe_cache(maxsize=2, ttl_seconds=100.0)
    def _expensive(value: int) -> int:
        calls["count"] += 1
        return value

    assert _expensive(1) == 1
    assert _expensive(2) == 2
    assert _expensive(3) == 3
    # key "1" should be evicted when maxsize is reached.
    assert _expensive(1) == 1
    assert calls["count"] == 4


def test_safe_execute_error_branches() -> None:
    adapter = psutil_adapter_module.PsutilAdapter()
    fallback: dict[str, bool] = {"ok": False}

    denied, _ = adapter._safe_execute(
        "denied",
        lambda: (_ for _ in ()).throw(psutil.AccessDenied()),
        fallback,
    )
    assert denied == fallback

    failed, _ = adapter._safe_execute(
        "failed",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        fallback,
    )
    assert failed == fallback
    adapter.close()


def test_safe_execute_timeout_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _new_adapter_without_warmup(monkeypatch)
    fallback: dict[str, bool] = {"timeout": True}

    def _slow_result() -> dict[str, bool]:
        time.sleep(0.05)
        return {"ok": True}

    timed_out, _ = adapter._safe_execute(
        "timeout",
        _slow_result,
        fallback,
        timeout=0.001,
    )
    assert timed_out == fallback
    adapter.close()


def test_adapter_del_swallows_runtime_close_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _new_adapter_without_warmup(monkeypatch)

    def _boom_close() -> None:
        raise RuntimeError("close failed")

    monkeypatch.setattr(adapter, "close", _boom_close)
    adapter.__del__()


def test_top_processes_validation() -> None:
    adapter = psutil_adapter_module.PsutilAdapter()
    with pytest.raises(ValueError):
        adapter.get_top_processes(count=0)
    with pytest.raises(ValueError):
        adapter.get_top_processes(count=100)
    adapter.close()


def test_start_cpu_warmup_returns_when_thread_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = psutil_adapter_module.PsutilAdapter()

    class _AliveThread:
        @staticmethod
        def is_alive() -> bool:
            return True

        @staticmethod
        def join(timeout: float | None = None) -> None:
            del timeout
            return None

    adapter._cpu_warmup_thread = cast(threading.Thread, _AliveThread())
    adapter._start_cpu_warmup()
    adapter.close()


def test_cpu_warmup_worker_fallback_to_overall(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _new_adapter_without_warmup(monkeypatch)

    class _FakeStopEvent:
        def __init__(self) -> None:
            self._iterated = False

        def is_set(self) -> bool:
            return self._iterated

        def set(self) -> None:
            self._iterated = True

        def wait(self, timeout: float) -> bool:
            del timeout
            self._iterated = True
            return True

    class _WarmupPsutil:
        def cpu_percent(
            self, *, interval: float, percpu: bool = False
        ) -> float | list[float]:
            del interval
            if percpu:
                return []
            return 33.3

    adapter._cpu_warmup_stop_event = cast(threading.Event, _FakeStopEvent())
    monkeypatch.setattr(adapter, "_psutil", _WarmupPsutil())
    adapter._cpu_warmup_worker()
    assert adapter._cpu_usage_snapshot is not None
    assert adapter._cpu_usage_snapshot["cpu_percent"] == 33.3
    adapter.close()


def test_cpu_warmup_worker_logs_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _new_adapter_without_warmup(monkeypatch)

    class _FakeStopEvent:
        def __init__(self) -> None:
            self._iterated = False

        def is_set(self) -> bool:
            return self._iterated

        def set(self) -> None:
            self._iterated = True

        def wait(self, timeout: float) -> bool:
            del timeout
            self._iterated = True
            return True

    class _FailingWarmupPsutil:
        def cpu_percent(
            self, *, interval: float, percpu: bool = False
        ) -> float | list[float]:
            del interval, percpu
            raise RuntimeError("cpu boom")

    adapter._cpu_warmup_stop_event = cast(threading.Event, _FakeStopEvent())
    monkeypatch.setattr(adapter, "_psutil", _FailingWarmupPsutil())
    adapter._cpu_warmup_worker()
    adapter.close()


def test_health_summary_handles_missing_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _new_adapter_without_warmup(monkeypatch)

    class _NoProcessPsutil:
        def Process(self) -> psutil.Process:  # noqa: N802
            raise psutil.AccessDenied()

    monkeypatch.setattr(adapter, "_psutil", _NoProcessPsutil())
    _clear_cached_method(adapter.get_current_process_health_summary)
    assert adapter.get_current_process_health_summary() == {}
    adapter.close()


def test_load_and_disk_io_fallback_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _new_adapter_without_warmup(monkeypatch)

    class _FallbackPsutil:
        def getloadavg(self) -> tuple[float, float, float]:
            raise OSError("unsupported")

        def disk_io_counters(self, *, perdisk: bool) -> dict[str, SimpleNamespace]:
            del perdisk
            return {}

    monkeypatch.setattr(adapter, "_psutil", _FallbackPsutil())
    _clear_cached_method(adapter.get_load_average)
    _clear_cached_method(adapter.get_disk_io_stats)
    assert adapter.get_load_average() == (0.0, 0.0, 0.0)
    assert adapter.get_disk_io_stats() == []
    adapter.close()


def test_disk_io_counters_exception_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _new_adapter_without_warmup(monkeypatch)

    class _BrokenDiskIoPsutil:
        def disk_io_counters(self, *, perdisk: bool) -> dict[str, SimpleNamespace]:
            del perdisk
            raise RuntimeError("disk io unavailable")

    monkeypatch.setattr(adapter, "_psutil", _BrokenDiskIoPsutil())
    _clear_cached_method(adapter.get_disk_io_stats)
    assert adapter.get_disk_io_stats() == []
    adapter.close()


def test_temperature_and_fans_fallback_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _new_adapter_without_warmup(monkeypatch)

    class _FallbackSensorPsutil:
        def sensors_temperatures(self) -> dict[str, list[SimpleNamespace]]:
            return {}

        def sensors_fans(self) -> dict[str, list[SimpleNamespace]]:
            return {
                "chassis": [
                    SimpleNamespace(current=None, label="missing"),
                    SimpleNamespace(current=-10, label="bad"),
                ],
                "empty": [],
            }

    monkeypatch.setattr(adapter, "_psutil", _FallbackSensorPsutil())
    _clear_cached_method(adapter.get_sensors_temperatures)
    _clear_cached_method(adapter.get_fan_speeds)
    assert adapter.get_sensors_temperatures() == []
    assert adapter.get_fan_speeds() == []
    adapter.close()


def test_temperature_and_fans_exception_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _new_adapter_without_warmup(monkeypatch)

    class _BrokenSensorPsutil:
        def sensors_temperatures(self) -> dict[str, list[SimpleNamespace]]:
            raise OSError("temps unavailable")

        def sensors_fans(self) -> dict[str, list[SimpleNamespace]]:
            raise RuntimeError("fans unavailable")

    monkeypatch.setattr(adapter, "_psutil", _BrokenSensorPsutil())
    _clear_cached_method(adapter.get_sensors_temperatures)
    _clear_cached_method(adapter.get_fan_speeds)
    assert adapter.get_sensors_temperatures() == []
    assert adapter.get_fan_speeds() == []
    adapter.close()


def test_fan_speeds_empty_and_oserror_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _new_adapter_without_warmup(monkeypatch)

    class _EmptyFansPsutil:
        @staticmethod
        def sensors_fans() -> dict[str, list[SimpleNamespace]]:
            return {}

    monkeypatch.setattr(adapter, "_psutil", _EmptyFansPsutil())
    _clear_cached_method(adapter.get_fan_speeds)
    assert adapter.get_fan_speeds() == []

    class _OSErrorFansPsutil:
        @staticmethod
        def sensors_fans() -> dict[str, list[SimpleNamespace]]:
            raise OSError("fans unsupported")

    monkeypatch.setattr(adapter, "_psutil", _OSErrorFansPsutil())
    _clear_cached_method(adapter.get_fan_speeds)
    assert adapter.get_fan_speeds() == []
    adapter.close()


def test_process_counts_and_network_summary_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _new_adapter_without_warmup(monkeypatch)

    class _CountPsutil:
        def process_iter(self, attrs: list[str]) -> list[SimpleNamespace]:
            del attrs
            return [SimpleNamespace(info={"status": "blocked"})]

        def net_connections(self, kind: str | None = None) -> list[SimpleNamespace]:
            if kind is not None:
                raise TypeError("kind unsupported")
            return [SimpleNamespace(status="ESTABLISHED", type=socket.SOCK_STREAM)]

    monkeypatch.setattr(adapter, "_psutil", _CountPsutil())
    _clear_cached_method(adapter.get_process_counts)
    _clear_cached_method(adapter.get_network_connections_summary)
    counts = adapter.get_process_counts()
    summary = adapter.get_network_connections_summary()
    assert counts["total"] == 1
    assert summary["tcp"] == 1

    class _BrokenCountPsutil:
        def process_iter(self, attrs: list[str]) -> list[SimpleNamespace]:
            del attrs
            raise RuntimeError("iter fail")

        def net_connections(self, kind: str = "inet") -> list[SimpleNamespace]:
            del kind
            raise RuntimeError("connections fail")

    monkeypatch.setattr(adapter, "_psutil", _BrokenCountPsutil())
    _clear_cached_method(adapter.get_process_counts)
    _clear_cached_method(adapter.get_network_connections_summary)
    assert adapter.get_process_counts() == {
        "running": 0,
        "sleeping": 0,
        "idle": 0,
        "total": 0,
    }
    assert adapter.get_network_connections_summary() == {
        "total": 0,
        "tcp": 0,
        "udp": 0,
        "statuses": {},
    }
    adapter.close()


def test_net_io_users_interfaces_and_cpu_fallbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _new_adapter_without_warmup(monkeypatch)

    class _FallbackPsutil:
        def net_io_counters(self) -> SimpleNamespace | None:
            return None

        def users(self) -> list[SimpleNamespace]:
            raise RuntimeError("users fail")

        def net_if_stats(self) -> dict[str, SimpleNamespace]:
            raise RuntimeError("iface fail")

        def net_if_addrs(self) -> dict[str, list[SimpleNamespace]]:
            return {}

        def cpu_freq(self) -> SimpleNamespace | None:
            return None

        def cpu_percent(
            self, *, interval: float, percpu: bool = False
        ) -> float | list[float]:
            del interval
            if percpu:
                return []
            return 7.0

        def cpu_times_percent(self, *, interval: float) -> SimpleNamespace:
            del interval
            raise OSError("cpu times unsupported")

    monkeypatch.setattr(adapter, "_psutil", _FallbackPsutil())
    _clear_cached_method(adapter.get_net_io_counters)
    _clear_cached_method(adapter.get_users_info)
    _clear_cached_method(adapter.get_net_interface_stats)
    _clear_cached_method(adapter.get_cpu_frequency)
    _clear_cached_method(adapter.get_cpu_times_percent)
    assert adapter.get_net_io_counters() == []
    assert adapter.get_users_info() == []
    assert adapter.get_net_interface_stats() == {}
    assert adapter.get_cpu_frequency() == {
        "current_freq": 0.0,
        "min_freq": 0.0,
        "max_freq": 0.0,
    }
    # force uncached branch of get_cpu_usage with empty per-core values
    adapter._cpu_usage_snapshot = None
    assert adapter.get_cpu_usage()["cpu_percent"] == 7.0
    assert adapter.get_cpu_times_percent() == {
        "user": 0.0,
        "system": 0.0,
        "idle": 0.0,
        "iowait": 0.0,
        "irq": 0.0,
        "softirq": 0.0,
    }
    adapter.close()


def test_cpu_frequency_attribute_error_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _new_adapter_without_warmup(monkeypatch)

    class _AttrErrPsutil:
        def cpu_freq(self) -> SimpleNamespace:
            raise AttributeError("no cpu freq")

    monkeypatch.setattr(adapter, "_psutil", _AttrErrPsutil())
    _clear_cached_method(adapter.get_cpu_frequency)
    assert adapter.get_cpu_frequency()["current_freq"] == 0.0
    adapter.close()
