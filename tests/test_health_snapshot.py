from __future__ import annotations

import io
import json
import os
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Generator
from pathlib import Path
from types import SimpleNamespace
from typing import NoReturn

import psutil
import pytest

import pytmbot.health_system.probe as probe_module
from pytmbot.health_system.snapshot import (
    SNAPSHOT_FILENAME,
    SNAPSHOT_MAX_BYTES,
    HealthSnapshot,
    HealthSnapshotWriter,
    ProbeStatus,
    evaluate_health_snapshot,
    get_health_snapshot_path,
    snapshot_ttl,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
_CURRENT_PROCESS = psutil.Process()


@pytest.fixture
def state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "state"
    monkeypatch.setenv("PYTMBOT_STATE_DIR", str(directory))
    return directory


def _payload(**overrides: object) -> dict[str, object]:
    now = time.time()
    payload: dict[str, object] = {
        "schema": 1,
        "pid": os.getpid(),
        "process_create_time": _CURRENT_PROCESS.create_time(),
        "overall": "healthy",
        "healthy": True,
        "timestamp": now,
        "stale_after": now + snapshot_ttl(120.0),
        "components": {"telegram_api": "healthy", "polling": "healthy"},
    }
    payload.update(overrides)
    return payload


def _store(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _wait_for(condition: Callable[[], bool], timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.01)
    return condition()


@pytest.fixture
def exited_child() -> Generator[subprocess.Popen[bytes], None, None]:
    child = subprocess.Popen([sys.executable, "-c", "pass"])
    yield child
    child.wait()


def test_snapshot_path_follows_the_state_directory(state_dir: Path) -> None:
    assert get_health_snapshot_path() == state_dir / SNAPSHOT_FILENAME
    assert HealthSnapshotWriter().path == state_dir / SNAPSHOT_FILENAME


def test_writer_publishes_private_snapshot_of_current_process(state_dir: Path) -> None:
    writer = HealthSnapshotWriter()

    before = time.time()
    snapshot = writer.write(
        overall="degraded",
        healthy=True,
        components={"telegram_api": "healthy", "sessions": "unhealthy"},
        interval_seconds=120.0,
    )

    assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(writer.path.stat().st_mode) == 0o600
    payload = json.loads(writer.path.read_text(encoding="utf-8"))
    assert payload == snapshot.to_payload()
    assert payload["schema"] == 1
    assert payload["pid"] == os.getpid()
    assert payload["process_create_time"] == pytest.approx(
        _CURRENT_PROCESS.create_time(), abs=1.0
    )
    assert payload["overall"] == "degraded"
    assert payload["healthy"] is True
    assert before <= payload["timestamp"] <= time.time()
    assert payload["stale_after"] == pytest.approx(payload["timestamp"] + 300.0)
    assert payload["components"] == {"telegram_api": "healthy", "sessions": "unhealthy"}
    assert HealthSnapshot.from_payload(payload) == snapshot
    assert [entry.name for entry in state_dir.iterdir()] == [SNAPSHOT_FILENAME]


def test_writer_replaces_atomically_and_cleans_up_on_failure(
    state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    writer = HealthSnapshotWriter()
    writer.write(overall="healthy", healthy=True, components={}, interval_seconds=60)
    previous = writer.path.read_bytes()

    def _failing_replace(src: str, dst: Path) -> NoReturn:
        del src, dst
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("pytmbot.health_system.snapshot.os.replace", _failing_replace)
    with pytest.raises(OSError):
        writer.write(
            overall="critical", healthy=False, components={}, interval_seconds=60
        )

    # Readers keep seeing the last complete snapshot and no temp file is left.
    assert writer.path.read_bytes() == previous
    assert [entry.name for entry in state_dir.iterdir()] == [SNAPSHOT_FILENAME]


def test_writer_raises_when_state_directory_is_not_writable(tmp_path: Path) -> None:
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("", encoding="utf-8")
    writer = HealthSnapshotWriter(blocker / "health.json")

    with pytest.raises(OSError):
        writer.write(overall="healthy", healthy=True, components={}, interval_seconds=1)


def test_writer_remove_is_best_effort(state_dir: Path) -> None:
    writer = HealthSnapshotWriter()
    writer.write(overall="healthy", healthy=True, components={}, interval_seconds=60)

    writer.remove()
    writer.remove()

    assert not writer.path.exists()


def test_probe_reports_fresh_snapshot_of_live_bot_as_healthy(state_dir: Path) -> None:
    _store(state_dir / SNAPSHOT_FILENAME, _payload())

    result = evaluate_health_snapshot()

    assert result.status is ProbeStatus.HEALTHY
    assert "bot reports healthy" in result.reason


def test_probe_reports_missing_snapshot_as_unknown(state_dir: Path) -> None:
    result = evaluate_health_snapshot()

    assert result.status is ProbeStatus.UNKNOWN
    assert "no health snapshot" in result.reason
    assert str(state_dir / SNAPSHOT_FILENAME) in result.reason


def test_probe_reports_stale_snapshot_as_unhealthy(state_dir: Path) -> None:
    now = time.time()
    path = _store(
        state_dir / SNAPSHOT_FILENAME,
        _payload(timestamp=now - 400.0, stale_after=now - 100.0),
    )

    result = evaluate_health_snapshot(path, now=now)

    assert result.status is ProbeStatus.UNHEALTHY
    assert "stale: last update 400s ago" in result.reason


def test_probe_reports_snapshot_from_the_future_as_unhealthy(state_dir: Path) -> None:
    now = time.time()
    path = _store(
        state_dir / SNAPSHOT_FILENAME,
        _payload(timestamp=now + 3600.0, stale_after=now + 3900.0),
    )

    result = evaluate_health_snapshot(path, now=now)

    assert result.status is ProbeStatus.UNHEALTHY
    assert "in the future" in result.reason


def test_probe_reports_unhealthy_level_with_failing_components(
    state_dir: Path,
) -> None:
    path = _store(
        state_dir / SNAPSHOT_FILENAME,
        _payload(
            overall="unhealthy",
            healthy=False,
            components={"telegram_api": "unhealthy", "polling": "healthy"},
        ),
    )

    result = evaluate_health_snapshot(path)

    assert result.status is ProbeStatus.UNHEALTHY
    assert result.reason == "bot reports unhealthy: telegram_api=unhealthy"


def test_probe_reports_dead_writer_process_as_unhealthy(
    state_dir: Path, exited_child: subprocess.Popen[bytes]
) -> None:
    exited_child.wait()
    path = _store(state_dir / SNAPSHOT_FILENAME, _payload(pid=exited_child.pid))

    result = evaluate_health_snapshot(path)

    assert result.status is ProbeStatus.UNHEALTHY
    # The PID is either free or, rarely, already reused by another process.
    assert "is not running" in result.reason or "another process" in result.reason


def test_probe_reports_zombie_writer_process_as_unhealthy(
    state_dir: Path, exited_child: subprocess.Popen[bytes]
) -> None:
    child = psutil.Process(exited_child.pid)
    create_time = child.create_time()
    # Not reaped yet: the exited child stays a zombie until the fixture waits for it.
    assert _wait_for(lambda: child.status() == psutil.STATUS_ZOMBIE)
    path = _store(
        state_dir / SNAPSHOT_FILENAME,
        _payload(pid=exited_child.pid, process_create_time=create_time),
    )

    result = evaluate_health_snapshot(path)

    assert result.status is ProbeStatus.UNHEALTHY
    assert result.reason == (
        f"bot process {exited_child.pid} that wrote the health snapshot is not running"
    )


def test_probe_reports_reused_pid_as_unhealthy(state_dir: Path) -> None:
    path = _store(
        state_dir / SNAPSHOT_FILENAME,
        _payload(process_create_time=_CURRENT_PROCESS.create_time() - 3600.0),
    )

    result = evaluate_health_snapshot(path)

    assert result.status is ProbeStatus.UNHEALTHY
    assert "now belongs to another process" in result.reason


def test_probe_reports_uninspectable_process_as_unhealthy(
    state_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _store(state_dir / SNAPSHOT_FILENAME, _payload())

    def _denied(pid: int) -> NoReturn:
        raise psutil.AccessDenied(pid)

    monkeypatch.setattr("pytmbot.health_system.snapshot.psutil.Process", _denied)

    result = evaluate_health_snapshot(path)

    assert result.status is ProbeStatus.UNHEALTHY
    assert "cannot inspect bot process" in result.reason


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"{not json", "invalid health snapshot"),
        (b"\xff\xfe", "invalid health snapshot"),
        (b"[]", "must be a JSON object"),
        (b" " * (SNAPSHOT_MAX_BYTES + 1), "larger than"),
    ],
)
def test_probe_reports_corrupt_snapshot_as_unhealthy(
    state_dir: Path, content: bytes, message: str
) -> None:
    path = state_dir / SNAPSHOT_FILENAME
    path.parent.mkdir(parents=True)
    path.write_bytes(content)

    result = evaluate_health_snapshot(path)

    assert result.status is ProbeStatus.UNHEALTHY
    assert message in result.reason


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"schema": 2}, "unsupported schema version 2"),
        ({"schema": True}, "'schema' must be an integer"),
        ({"pid": 0}, "'pid' must be a positive integer"),
        ({"pid": True}, "'pid' must be a positive integer"),
        ({"overall": ""}, "'overall' must be a non-empty string"),
        ({"healthy": "yes"}, "'healthy' must be a boolean"),
        ({"timestamp": "now"}, "'timestamp' must be a number"),
        ({"process_create_time": float("nan")}, "must be finite"),
        ({"stale_after": 0.0}, "earlier than 'timestamp'"),
        ({"components": ["telegram_api"]}, "'components' must map"),
        ({"components": {"telegram_api": 100}}, "'components' must map"),
    ],
)
def test_probe_reports_invalid_snapshot_fields_as_unhealthy(
    state_dir: Path, overrides: dict[str, object], message: str
) -> None:
    path = _store(state_dir / SNAPSHOT_FILENAME, _payload(**overrides))

    result = evaluate_health_snapshot(path)

    assert result.status is ProbeStatus.UNHEALTHY
    assert message in result.reason


def test_probe_reports_unreadable_snapshot_as_unhealthy(state_dir: Path) -> None:
    (state_dir / SNAPSHOT_FILENAME).mkdir(parents=True)

    result = evaluate_health_snapshot()

    assert result.status is ProbeStatus.UNHEALTHY
    assert "cannot read health snapshot" in result.reason


def test_run_probe_prints_reason_only_on_failure(
    state_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert probe_module.run_probe() == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("pytmbot health check: no health snapshot")
    assert captured.err.count("\n") == 1

    _store(state_dir / SNAPSHOT_FILENAME, _payload())
    assert probe_module.run_probe() == 0
    assert capsys.readouterr() == ("", "")


@pytest.mark.usefixtures("state_dir")
def test_probe_main_exits_with_probe_code() -> None:
    with pytest.raises(SystemExit) as exc_info:
        probe_module.main()
    assert exc_info.value.code == 2


def test_exit_probe_bypasses_system_exit_in_inspect_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exits: list[int] = []

    class _ProcessExited(Exception):
        pass

    def _fake_exit(code: int) -> NoReturn:
        exits.append(code)
        raise _ProcessExited

    monkeypatch.setattr(
        probe_module,
        "sys",
        SimpleNamespace(
            flags=SimpleNamespace(inspect=1),
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        ),
    )
    monkeypatch.setattr(os, "_exit", _fake_exit)

    with pytest.raises(_ProcessExited):
        probe_module.exit_probe(2)
    assert exits == [2]


def _run_probe_process(
    state_dir: Path, *extra_args: str
) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "PYTHONPATH": str(REPO_ROOT),
        "PYTMBOT_STATE_DIR": str(state_dir),
        # The Docker image sets PYTHONINSPECT=0, which enables inspect mode.
        "PYTHONINSPECT": "0",
    }
    return subprocess.run(
        [sys.executable, *extra_args],
        cwd=REPO_ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


@pytest.mark.parametrize(
    "args",
    [
        ("-m", "pytmbot.health_system.probe"),
        ("pytmbot/main.py", "--health_check"),
    ],
    ids=["probe-module", "main-cli"],
)
def test_probe_process_exits_cleanly_under_inspect_mode(
    state_dir: Path, args: tuple[str, ...]
) -> None:
    missing = _run_probe_process(state_dir, *args)

    assert missing.returncode == 2, missing.stderr
    assert "Traceback" not in missing.stderr
    assert missing.stderr.startswith("pytmbot health check: no health snapshot")

    _store(state_dir / SNAPSHOT_FILENAME, _payload())
    healthy = _run_probe_process(state_dir, *args)

    assert healthy.returncode == 0, healthy.stderr
    assert "Traceback" not in healthy.stderr


def test_probe_module_stays_light() -> None:
    heavy = [
        "telebot",
        "loguru",
        "pydantic",
        "docker",
        "requests",
        "pytmbot.settings",
        "pytmbot.logs",
        "pytmbot.health_system.health_system",
    ]
    code = (
        "import sys, pytmbot.health_system.probe\n"
        f"print([name for name in {heavy!r} if name in sys.modules])\n"
    )

    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env={**os.environ, "PYTHONPATH": str(REPO_ROOT)},
        capture_output=True,
        text=True,
        timeout=60,
        check=True,
    )

    assert completed.stdout.strip() == "[]"
