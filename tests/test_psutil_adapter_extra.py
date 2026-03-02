from __future__ import annotations

import concurrent.futures
import socket
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace, TracebackType
from typing import Literal, cast

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


@dataclass
class _FakeFullMemoryInfo:
    uss: int = 3000
    pss: int = 4000


@dataclass
class _FakeProcess:
    pid: int

    def name(self) -> str:
        return "proc"

    def status(self) -> str:
        return "running"

    def create_time(self) -> float:
        return 100.0

    def parent(self) -> SimpleNamespace | None:
        return SimpleNamespace(pid=1)

    def cpu_percent(self, *, interval: float) -> float:
        del interval
        return 11.1

    def cpu_times(self) -> _FakeCpuTimes:
        return _FakeCpuTimes()

    def cpu_affinity(self) -> list[int]:
        return [0, 1]

    def cpu_num(self) -> int:
        return 0

    def memory_info(self) -> _FakeMemoryInfo:
        return _FakeMemoryInfo()

    def memory_percent(self) -> float:
        return 7.7

    def memory_full_info(self) -> _FakeFullMemoryInfo:
        return _FakeFullMemoryInfo()

    def memory_maps(self) -> list[SimpleNamespace]:
        return [SimpleNamespace(path="/tmp/a"), SimpleNamespace(path="/tmp/b")]

    def io_counters(self) -> _FakeIoCounters:
        return _FakeIoCounters()

    def num_threads(self) -> int:
        return 3

    def num_fds(self) -> int:
        return 9

    def net_connections(self) -> list[SimpleNamespace]:
        return [SimpleNamespace(status="ESTABLISHED"), SimpleNamespace(status="LISTEN")]

    def num_ctx_switches(self) -> _FakeCtxSwitches:
        return _FakeCtxSwitches()

    def cwd(self) -> str:
        return "/tmp"

    def cmdline(self) -> list[str]:
        return ["python", "main.py"]

    def exe(self) -> str:
        return "/usr/bin/python"


class _FakePsutil:
    AccessDenied = psutil.AccessDenied
    NoSuchProcess = psutil.NoSuchProcess

    def Process(self, pid: int | None = None) -> _FakeProcess:  # noqa: N802
        return _FakeProcess(pid or 999)

    def getloadavg(self) -> tuple[float, float, float]:
        return (0.1, 0.2, 0.3)

    def virtual_memory(self) -> SimpleNamespace:
        return SimpleNamespace(
            total=4096,
            available=2048,
            percent=50.0,
            used=2048,
            free=2048,
            active=100,
            inactive=200,
            cached=300,
            shared=400,
        )

    def disk_partitions(self, *, all: bool) -> list[SimpleNamespace]:
        del all
        return [SimpleNamespace(device="/dev/disk1", fstype="apfs", mountpoint="/")]

    def disk_usage(self, mountpoint: str) -> SimpleNamespace:
        del mountpoint
        return SimpleNamespace(total=10000, used=5000, free=5000, percent=50.0)

    def swap_memory(self) -> SimpleNamespace:
        return SimpleNamespace(total=1000, used=100, free=900, percent=10.0)

    def sensors_temperatures(self) -> dict[str, list[SimpleNamespace]]:
        return {"cpu": [SimpleNamespace(current=55.0)]}

    def process_iter(self, attrs: list[str]) -> list[SimpleNamespace]:
        if "status" in attrs and "pid" not in attrs:
            return [
                SimpleNamespace(info={"status": "running"}),
                SimpleNamespace(info={"status": "sleeping"}),
                SimpleNamespace(info={"status": "idle"}),
            ]
        return [
            SimpleNamespace(
                info={
                    "pid": 1,
                    "name": "a",
                    "cpu_percent": 10.0,
                    "memory_percent": 5.0,
                    "status": "running",
                }
            ),
            SimpleNamespace(
                info={
                    "pid": 2,
                    "name": "b",
                    "cpu_percent": 0.0,
                    "memory_percent": 0.0,
                    "status": "zombie",
                }
            ),
        ]

    def net_io_counters(self) -> SimpleNamespace:
        return SimpleNamespace(
            bytes_sent=1234,
            bytes_recv=5678,
            packets_sent=11,
            packets_recv=22,
            errin=0,
            errout=0,
            dropin=0,
            dropout=0,
        )

    def disk_io_counters(self, *, perdisk: bool) -> dict[str, SimpleNamespace]:
        del perdisk
        return {
            "sda": SimpleNamespace(
                read_bytes=1024,
                write_bytes=2048,
                read_count=10,
                write_count=20,
                read_time=30,
                write_time=40,
            )
        }

    def cpu_times_percent(self, *, interval: float) -> SimpleNamespace:
        del interval
        return SimpleNamespace(
            user=10.0,
            system=5.0,
            idle=80.0,
            iowait=2.0,
            irq=1.0,
            softirq=2.0,
        )

    def net_connections(self, kind: str = "inet") -> list[SimpleNamespace]:
        del kind
        return [
            SimpleNamespace(status="ESTABLISHED", type=socket.SOCK_STREAM),
            SimpleNamespace(status="LISTEN", type=socket.SOCK_STREAM),
            SimpleNamespace(status="NONE", type=socket.SOCK_DGRAM),
        ]

    def sensors_fans(self) -> dict[str, list[SimpleNamespace]]:
        return {"chassis": [SimpleNamespace(current=1200.0, label="fan1")]}

    def users(self) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(name="den", terminal="tty", host="localhost", started=1.0)
        ]

    def net_if_stats(self) -> dict[str, SimpleNamespace]:
        return {"eth0": SimpleNamespace(isup=True, speed=1000, duplex="full", mtu=1500)}

    def net_if_addrs(self) -> dict[str, list[SimpleNamespace]]:
        return {
            "eth0": [
                SimpleNamespace(
                    family=SimpleNamespace(name="AF_INET"),
                    address="127.0.0.1",
                )
            ]
        }

    def cpu_freq(self) -> SimpleNamespace:
        return SimpleNamespace(current=2800.0, min=1000.0, max=3500.0)

    def cpu_percent(
        self, *, interval: float, percpu: bool = False
    ) -> float | list[float]:
        del interval
        if percpu:
            return [10.0, 20.0]
        return 15.0

    def cpu_count(self, *, logical: bool) -> int | None:
        return 8 if logical else 4


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


def test_psutil_adapter_core_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = psutil_adapter_module.PsutilAdapter()
    fake_psutil = _FakePsutil()
    monkeypatch.setattr(adapter, "_psutil", fake_psutil)
    monkeypatch.setattr(
        psutil_adapter_module, "set_naturalsize", lambda value: f"{value}B"
    )
    monkeypatch.setattr(psutil, "boot_time", lambda: 0.0)

    process_stats = adapter.get_process_stats(pid=123)
    health = adapter.get_current_process_health_summary()
    load = adapter.get_load_average()
    memory = adapter.get_memory()
    disks = adapter.get_disk_usage()
    swap = adapter.get_swap_memory()
    sensors = adapter.get_sensors_temperatures()
    uptime = adapter.get_uptime()
    process_counts = adapter.get_process_counts()
    network_io = adapter.get_net_io_counters()
    disk_io = adapter.get_disk_io_stats()
    connections_summary = adapter.get_network_connections_summary()
    users = adapter.get_users_info()
    net_stats = adapter.get_net_interface_stats()
    cpu_freq = adapter.get_cpu_frequency()
    cpu_usage = adapter.get_cpu_usage()
    cpu_times = adapter.get_cpu_times_percent()
    top = adapter.get_top_processes(count=5)
    cpu_count = adapter.get_cpu_count()
    cpu_count_physical = adapter.get_cpu_count_physical()
    fans = adapter.get_fan_speeds()
    summary = adapter.get_system_summary()

    assert process_stats["pid"] == 123
    assert "cpu" in health
    assert load == (0.1, 0.2, 0.3)
    assert memory["percent"] == 50.0
    assert disks[0]["percent"] == 50.0
    assert swap["percent"] == 10.0
    assert sensors[0]["sensor_name"] == "cpu"
    assert isinstance(uptime, str)
    assert process_counts["total"] == 3
    assert network_io[0]["packets_sent"] == 11
    assert disk_io[0]["device_name"] == "sda"
    assert connections_summary["tcp"] == 2
    assert users[0]["username"] == "den"
    assert net_stats["eth0"]["ip_address"] == "127.0.0.1"
    assert cpu_freq["current_freq"] == 2800.0
    assert cpu_usage["cpu_percent"] == 15.0
    assert cpu_times["iowait"] == 2.0
    assert top[0]["pid"] == 1
    assert cpu_count == 8
    assert cpu_count_physical == 4
    assert fans[0]["rpm"] == 1200
    assert "cpu" in summary

    adapter.clear_cache()
    adapter.close()


def test_top_processes_validation_and_connections_counter() -> None:
    adapter = psutil_adapter_module.PsutilAdapter()
    with pytest.raises(ValueError):
        adapter.get_top_processes(count=0)
    with pytest.raises(ValueError):
        adapter.get_top_processes(count=100)

    counts = adapter._count_connections_by_status(
        [SimpleNamespace(status="LISTEN"), SimpleNamespace(status="LISTEN")]
    )
    assert counts["LISTEN"] == 2
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


def test_get_process_stats_invalid_pid_and_inaccessible_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _new_adapter_without_warmup(monkeypatch)

    with pytest.raises(ValueError):
        adapter.get_process_stats(pid=0)

    class _NoAccessPsutil:
        def Process(self, _pid: int) -> psutil.Process:  # noqa: N802
            raise psutil.AccessDenied()

    monkeypatch.setattr(adapter, "_psutil", _NoAccessPsutil())
    assert adapter.get_process_stats(pid=123) == {}
    adapter.close()


def test_collect_stats_concurrently_handles_timeout_and_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _new_adapter_without_warmup(monkeypatch)

    class _FakeFuture:
        def __init__(self, result: dict[str, int] | Exception) -> None:
            self._result = result

        def result(self, timeout: float | None = None) -> dict[str, int]:
            del timeout
            if isinstance(self._result, Exception):
                raise self._result
            return self._result

    class _FakeExecutor:
        def __init__(self) -> None:
            self.futures: list[_FakeFuture] = []

        def __enter__(self) -> _FakeExecutor:
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc: BaseException | None,
            tb: TracebackType | None,
        ) -> Literal[False]:
            del exc_type, exc, tb
            return False

        def submit(self, collector: Callable[[], dict[str, int]]) -> _FakeFuture:
            del collector
            if not self.futures:
                future = _FakeFuture(concurrent.futures.TimeoutError())
            else:
                future = _FakeFuture(RuntimeError("collector failed"))
            self.futures.append(future)
            return future

    fake_executor = _FakeExecutor()
    monkeypatch.setattr(
        concurrent.futures,
        "ThreadPoolExecutor",
        lambda *args, **kwargs: fake_executor,
    )
    monkeypatch.setattr(
        concurrent.futures,
        "as_completed",
        lambda future_to_name, timeout: list(future_to_name.keys()),
    )

    result = adapter._collect_stats_concurrently(
        [("slow", lambda: {"a": 1}), ("boom", lambda: {"b": 2})]
    )
    assert result == {}
    adapter.close()


def test_process_specific_collector_edge_cases(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _new_adapter_without_warmup(monkeypatch)

    class _NoFdsProcess:
        pid = 1

        def num_threads(self) -> int:
            return 1

        def num_handles(self) -> int:
            raise psutil.AccessDenied()

        def net_connections(self) -> list[SimpleNamespace]:
            raise psutil.AccessDenied()

        def cwd(self) -> str:
            return "/tmp"

        def cmdline(self) -> list[str]:
            return []

        def exe(self) -> str:
            return "/bin/sh"

    process = cast(psutil.Process, _NoFdsProcess())
    file_stats = adapter._get_process_file_stats(process)
    net_stats = adapter._get_process_network_stats(process)
    path_stats = adapter._get_process_path_stats(process)

    assert file_stats["num_fds"] == "N/A"
    assert "num_handles" not in file_stats
    assert net_stats == {"num_connections": 0, "connections_by_status": {}}
    assert path_stats["cmdline"] == "<no command line>"
    adapter.close()


def test_process_path_stats_truncates_long_cmdline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _new_adapter_without_warmup(monkeypatch)

    class _LongCmdProcess:
        pid = 1

        def cwd(self) -> str:
            return "/tmp"

        def cmdline(self) -> list[str]:
            return ["python", "x" * 200]

        def exe(self) -> str:
            return "/usr/bin/python"

    process = cast(psutil.Process, _LongCmdProcess())
    stats = adapter._get_process_path_stats(process)
    assert str(stats["cmdline"]).endswith("...")
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


def test_top_processes_and_clear_cache_and_summary_error_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _new_adapter_without_warmup(monkeypatch)

    class _TopBrokenPsutil:
        def process_iter(self, attrs: list[str]) -> list[SimpleNamespace]:
            del attrs
            raise RuntimeError("process iterator failed")

    monkeypatch.setattr(adapter, "_psutil", _TopBrokenPsutil())
    assert adapter.get_top_processes() == []

    class _BadCacheMethod:
        __wrapped__ = True

        @staticmethod
        def cache_clear() -> None:
            raise AttributeError("no cache clear")

    adapter.bad_cache_method = _BadCacheMethod()  # type: ignore[attr-defined]
    adapter.clear_cache()

    monkeypatch.setattr(
        adapter,
        "get_memory",
        lambda: (_ for _ in ()).throw(RuntimeError("memory fail")),
    )
    summary = adapter.get_system_summary()
    assert "cpu" in summary
    assert "memory" not in summary
    adapter.close()
