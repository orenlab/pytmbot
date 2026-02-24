from __future__ import annotations

import socket
from dataclasses import dataclass
from types import SimpleNamespace

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

    def memory_maps(self) -> list[object]:
        return [object(), object()]

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


def test_thread_safe_cache_respects_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    clock = [100.0]
    monkeypatch.setattr(psutil_adapter_module.time, "time", lambda: clock[0])
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


def test_safe_execute_error_branches() -> None:
    adapter = psutil_adapter_module.PsutilAdapter()
    fallback: dict[str, object] = {"ok": False}

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


def test_psutil_adapter_core_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = psutil_adapter_module.PsutilAdapter()
    fake_psutil = _FakePsutil()
    monkeypatch.setattr(adapter, "_psutil", fake_psutil)
    monkeypatch.setattr(
        psutil_adapter_module, "set_naturalsize", lambda value: f"{value}B"
    )
    monkeypatch.setattr(psutil_adapter_module.psutil, "boot_time", lambda: 0.0)

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
