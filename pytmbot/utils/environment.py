#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import os
import sys
from functools import cache
from pathlib import Path
from typing import Final, Literal, TypedDict

type MetricScope = Literal["host", "container", "unknown"]


class MetricScopes(TypedDict):
    """Whose numbers each metric group shows when the bot runs in Docker."""

    cpu: MetricScope
    memory: MetricScope
    processes: MetricScope
    disks: MetricScope
    disk_io: MetricScope
    network: MetricScope


_PROC_ROOT: Path = Path("/proc")
_HOST_PID_2_COMM: Final[str] = "kthreadd"

_PROCESS_NOTES: Final[dict[MetricScope, str]] = {
    "host": "Processes: whole host (shared PID namespace).",
    "container": "Processes: this container only (no pid: host).",
    "unknown": "Processes: could not tell whether these are the host's or this container's.",
}
_NETWORK_NOTES: Final[dict[MetricScope, str]] = {
    "host": "Network: whole host (host networking).",
    "container": "Network: this container's interfaces, not the host's.",
    "unknown": "Network: this container's interfaces, unless network_mode: host.",
}


@cache
def is_running_in_docker() -> bool:
    if os.path.exists("/.dockerenv"):
        return True
    try:
        with open("/proc/self/cgroup") as f:
            for line in f:
                if "docker" in line:
                    return True
    except OSError:
        pass
    if "DOCKER_CONTAINER" in os.environ:
        return True
    return False


def _read_proc_text(relative_path: str) -> str:
    return (_PROC_ROOT / relative_path).read_text(encoding="utf-8", errors="replace")


def _detect_process_scope() -> MetricScope:
    """
    Kernel threads are visible only in the host PID namespace, where PID 2 is
    always kthreadd. If PID 1 shares this process's mount table, PID 1 is this
    container's init, so the container has its own PID namespace. Anything else
    (hidden /proc entries, Docker nested in another container) stays unknown.
    """
    try:
        if _read_proc_text("2/comm").strip() == _HOST_PID_2_COMM:
            return "host"
    except OSError:
        pass
    try:
        init_mounts = _read_proc_text("1/mountinfo")
        own_mounts = _read_proc_text("self/mountinfo")
    except OSError:
        return "unknown"
    return "container" if init_mounts == own_mounts else "unknown"


def _detect_network_scope(process_scope: MetricScope) -> MetricScope:
    """
    Compare this process's network namespace with that of the host init (PID 1,
    meaningful only in the host PID namespace). Each network namespace has its own
    /proc/<pid>/net/dev entry with its own inode; unlike /proc/1/ns/net, it can be
    stat'ed without ptrace access to PID 1.
    """
    if process_scope != "host":
        return "unknown"
    try:
        host_init = (_PROC_ROOT / "1/net/dev").stat()
        own = (_PROC_ROOT / "self/net/dev").stat()
    except OSError:
        return "unknown"
    same_namespace = (host_init.st_dev, host_init.st_ino) == (own.st_dev, own.st_ino)
    return "host" if same_namespace else "container"


@cache
def get_docker_metric_scopes() -> MetricScopes | None:
    """
    Return whose numbers each metric group shows, or None outside Docker.

    CPU, memory and disk I/O counters (/proc/stat, /proc/meminfo, /proc/diskstats)
    are not namespaced, so they always describe the whole host. Disk usage covers
    only the filesystems mounted into the container.
    """
    if not is_running_in_docker():
        return None
    processes = _detect_process_scope()
    return {
        "cpu": "host",
        "memory": "host",
        "processes": processes,
        "disks": "container",
        "disk_io": "host",
        "network": _detect_network_scope(processes),
    }


def describe_metric_scopes(scopes: MetricScopes) -> dict[str, str]:
    """One-line notes saying whose numbers each server screen shows."""
    return {
        "cpu": "CPU: whole host, not this container's limit.",
        "memory": "Memory: whole host, not this container's limit.",
        "cpu_memory": "CPU and memory: whole host, not this container's limits.",
        "processes": _PROCESS_NOTES[scopes["processes"]],
        "disks": "Disks: only filesystems mounted into this container.",
        "disk_io": "Disk I/O: whole host (all block devices).",
        "network": _NETWORK_NOTES[scopes["network"]],
    }


def get_metric_scope_notes() -> dict[str, str]:
    """Scope notes for server screens when running in Docker; empty otherwise."""
    scopes = get_docker_metric_scopes()
    return describe_metric_scopes(scopes) if scopes is not None else {}


@cache
def get_environment_state() -> dict[str, object]:
    return {
        "Python path": sys.executable,
        "Python version": sys.version,
        "Module path": sys.path,
        "Command args": sys.argv,
        "Running on": "Docker" if is_running_in_docker() else "Bare Metal",
        "Metric scopes": get_docker_metric_scopes(),
    }
