from __future__ import annotations

import io
import os
from pathlib import Path

import pytest

import pytmbot.utils.environment as environment
from pytmbot.utils.environment import (
    MetricScope,
    MetricScopes,
    describe_metric_scopes,
    get_docker_metric_scopes,
    get_environment_state,
    get_metric_scope_notes,
    is_running_in_docker,
)

_CONTAINER_MOUNTS = "1301 1200 0:88 / / ro,relatime - overlay overlay rw\n"
_OUTER_MOUNTS = "22 1 8:1 / / rw,relatime shared:1 - ext4 /dev/sda1 rw\n"


def test_is_running_in_docker_true_when_dockerenv_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    is_running_in_docker.cache_clear()
    monkeypatch.setattr("os.path.exists", lambda _: True)
    assert is_running_in_docker() is True


def test_is_running_in_docker_true_from_cgroup(monkeypatch: pytest.MonkeyPatch) -> None:
    is_running_in_docker.cache_clear()
    monkeypatch.setattr("os.path.exists", lambda _: False)
    monkeypatch.delenv("DOCKER_CONTAINER", raising=False)
    monkeypatch.setattr("builtins.open", lambda *_a, **_k: io.StringIO("0::/docker/x"))
    assert is_running_in_docker() is True


def test_is_running_in_docker_true_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    is_running_in_docker.cache_clear()
    monkeypatch.setattr("os.path.exists", lambda _: False)
    monkeypatch.setattr("builtins.open", lambda *_a, **_k: io.StringIO("0::/"))
    monkeypatch.setenv("DOCKER_CONTAINER", "1")
    assert is_running_in_docker() is True


def test_get_environment_state_contains_required_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    get_environment_state.cache_clear()
    monkeypatch.setattr("pytmbot.utils.environment.is_running_in_docker", lambda: False)
    state = get_environment_state()
    assert state["Running on"] == "Bare Metal"
    assert state["Metric scopes"] is None
    assert "Python path" in state
    assert isinstance(state["Command args"], list)
    assert isinstance(state["Module path"], list)
    assert isinstance(state["Python version"], str)
    assert os.path.basename(str(state["Python path"])) in {
        "python",
        "python3",
        "python3.13",
    }


def _write(root: Path, relative_path: str, content: str = "") -> Path:
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


@pytest.fixture
def fake_proc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A /proc tree for a bot running in Docker; tests add the entries they need."""
    monkeypatch.setattr(environment, "_PROC_ROOT", tmp_path)
    monkeypatch.setattr(environment, "is_running_in_docker", lambda: True)
    _write(tmp_path, "self/mountinfo", _CONTAINER_MOUNTS)
    return tmp_path


def _scopes() -> MetricScopes:
    scopes = get_docker_metric_scopes()
    assert scopes is not None
    return scopes


def test_scopes_with_host_pid_namespace_and_bridge_network(fake_proc: Path) -> None:
    _write(fake_proc, "2/comm", "kthreadd\n")
    _write(fake_proc, "1/net/dev")
    _write(fake_proc, "self/net/dev")

    assert _scopes() == {
        "cpu": "host",
        "memory": "host",
        "processes": "host",
        "disks": "container",
        "disk_io": "host",
        "network": "container",
    }


def test_scopes_with_host_pid_namespace_and_host_network(fake_proc: Path) -> None:
    _write(fake_proc, "2/comm", "kthreadd\n")
    host_net_dev = _write(fake_proc, "1/net/dev")
    (fake_proc / "self/net").mkdir()
    (fake_proc / "self/net/dev").hardlink_to(host_net_dev)

    scopes = _scopes()
    assert scopes["processes"] == "host"
    assert scopes["network"] == "host"


def test_network_unknown_when_net_entries_unreadable(fake_proc: Path) -> None:
    _write(fake_proc, "2/comm", "kthreadd\n")

    assert _scopes()["network"] == "unknown"


def test_scopes_with_own_pid_namespace_and_visible_pid_2(fake_proc: Path) -> None:
    _write(fake_proc, "2/comm", "python3\n")
    _write(fake_proc, "1/mountinfo", _CONTAINER_MOUNTS)

    scopes = _scopes()
    assert scopes["processes"] == "container"
    # Without the host init there is nothing to compare the network namespace with.
    assert scopes["network"] == "unknown"


def test_scopes_with_own_pid_namespace_without_pid_2(fake_proc: Path) -> None:
    _write(fake_proc, "1/mountinfo", _CONTAINER_MOUNTS)

    assert _scopes()["processes"] == "container"


def test_process_scope_unknown_when_pid_1_is_outside_the_container(
    fake_proc: Path,
) -> None:
    # e.g. pid: host inside an LXC container: no kernel threads, PID 1 elsewhere.
    _write(fake_proc, "2/comm", "systemd-journal\n")
    _write(fake_proc, "1/mountinfo", _OUTER_MOUNTS)

    assert _scopes()["processes"] == "unknown"


def test_process_scope_unknown_when_proc_entries_are_hidden(fake_proc: Path) -> None:
    # hidepid: neither PID 1 nor PID 2 is visible.
    scopes = _scopes()
    assert scopes["processes"] == "unknown"
    assert scopes["network"] == "unknown"


def test_process_scope_unknown_when_proc_entries_are_unreadable(
    fake_proc: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(fake_proc, "2/comm", "kthreadd\n")
    _write(fake_proc, "1/mountinfo", _CONTAINER_MOUNTS)

    def _deny_other_pids(relative_path: str) -> str:
        if not relative_path.startswith("self/"):
            raise PermissionError(relative_path)
        return (fake_proc / relative_path).read_text()

    monkeypatch.setattr(environment, "_read_proc_text", _deny_other_pids)
    assert _scopes()["processes"] == "unknown"


def test_scopes_are_none_outside_docker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(environment, "is_running_in_docker", lambda: False)

    assert get_docker_metric_scopes() is None
    assert get_metric_scope_notes() == {}


def test_scopes_are_detected_once(
    fake_proc: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[None] = []

    def _detect() -> MetricScope:
        calls.append(None)
        return "host"

    monkeypatch.setattr(environment, "_detect_process_scope", _detect)
    assert get_docker_metric_scopes() is get_docker_metric_scopes()
    assert len(calls) == 1


def test_scopes_from_real_proc_are_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(environment, "is_running_in_docker", lambda: True)

    scopes = _scopes()
    assert scopes["processes"] in {"host", "container", "unknown"}
    assert scopes["network"] in {"host", "container", "unknown"}


@pytest.mark.parametrize(
    ("processes", "network", "process_note", "network_note"),
    [
        (
            "host",
            "container",
            "Processes: whole host (shared PID namespace).",
            "Network: this container's interfaces, not the host's.",
        ),
        (
            "host",
            "host",
            "Processes: whole host (shared PID namespace).",
            "Network: whole host (host networking).",
        ),
        (
            "container",
            "unknown",
            "Processes: this container only (no pid: host).",
            "Network: this container's interfaces, unless network_mode: host.",
        ),
        (
            "unknown",
            "unknown",
            "Processes: could not tell whether these are the host's or this "
            "container's.",
            "Network: this container's interfaces, unless network_mode: host.",
        ),
    ],
)
def test_describe_metric_scopes(
    processes: MetricScope,
    network: MetricScope,
    process_note: str,
    network_note: str,
) -> None:
    notes = describe_metric_scopes(
        {
            "cpu": "host",
            "memory": "host",
            "processes": processes,
            "disks": "container",
            "disk_io": "host",
            "network": network,
        }
    )

    assert notes["processes"] == process_note
    assert notes["network"] == network_note
    assert notes["cpu"] == "CPU: whole host, not this container's limit."
    assert notes["memory"] == "Memory: whole host, not this container's limit."
    assert notes["disks"] == "Disks: only filesystems mounted into this container."
    assert notes["disk_io"] == "Disk I/O: whole host (all block devices)."
    assert set(notes) == {
        "cpu",
        "memory",
        "cpu_memory",
        "processes",
        "disks",
        "disk_io",
        "network",
    }


def test_metric_scope_notes_in_docker(fake_proc: Path) -> None:
    _write(fake_proc, "2/comm", "kthreadd\n")

    notes = get_metric_scope_notes()
    assert notes["processes"] == "Processes: whole host (shared PID namespace)."
    assert notes == describe_metric_scopes(_scopes())
