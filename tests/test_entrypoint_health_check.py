from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from pytmbot.health_system.snapshot import HealthSnapshotWriter

REPO_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = REPO_ROOT / "entrypoint.sh"
PROBE_MODULE = "pytmbot.health_system.probe"

pytestmark = pytest.mark.skipif(
    shutil.which("sh") is None, reason="POSIX sh is required"
)

# Stands in for the image's Python: passes the "Python OK" check and answers the
# probe call with $STUB_RC.
_STUB_PYTHON = """#!/bin/sh
if [ "$1" = "-c" ]; then
    exit 0
fi
printf '%s\\n' "$*" >> "$STUB_CALLS"
echo "pytmbot health check: stub reason" >&2
exit "$STUB_RC"
"""


def _shell_function(name: str) -> str:
    script = ENTRYPOINT.read_text(encoding="utf-8")
    match = re.search(
        rf"^{name}\(\) \{{\n.*?^\}}\n", script, flags=re.MULTILINE | re.DOTALL
    )
    assert match is not None, f"{name}() not found in entrypoint.sh"
    return match.group(0)


def _write_harness(tmp_path: Path, python_path: str) -> Path:
    """Run entrypoint.sh's health_check() with its helpers under ``set -e``."""
    main_script = tmp_path / "main.py"
    main_script.write_text("", encoding="utf-8")
    harness = tmp_path / "health_check.sh"
    harness.write_text(
        "set -e\n"
        f"PYTHON_PATH='{python_path}'\n"
        f"MAIN_SCRIPT='{main_script}'\n"
        + _shell_function("log")
        + _shell_function("check_docker_access")
        + _shell_function("health_check")
        + "health_check\n",
        encoding="utf-8",
    )
    return harness


def _run_harness(
    harness: Path, env: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(harness)],
        cwd=REPO_ROOT,
        env={**os.environ, **env},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_health_check_no_longer_scans_processes() -> None:
    body = _shell_function("health_check")

    assert "/proc" not in body
    assert "cmdline" not in body
    assert '"$PYTHON_PATH" -m "$_health_probe"' in body
    assert f'_health_probe="{PROBE_MODULE}"' in body


@pytest.mark.parametrize(
    ("probe_rc", "expected_rc", "expected_message"),
    [
        (0, 0, "Health check passed"),
        (1, 1, "Health check failed: bot is unhealthy or its health snapshot is stale"),
        (2, 1, "Health check failed: no health data yet"),
        (3, 1, 'Unexpected health check exit code › {"source": '),
        (127, 1, '"code": 127}'),
    ],
)
def test_health_check_maps_probe_exit_codes(
    tmp_path: Path, probe_rc: int, expected_rc: int, expected_message: str
) -> None:
    stub = tmp_path / "python3"
    stub.write_text(_STUB_PYTHON, encoding="utf-8")
    stub.chmod(0o755)
    calls = tmp_path / "calls.log"

    completed = _run_harness(
        _write_harness(tmp_path, str(stub)),
        {"STUB_RC": str(probe_rc), "STUB_CALLS": str(calls)},
    )

    assert completed.returncode == expected_rc, completed.stdout + completed.stderr
    assert expected_message in completed.stdout
    assert calls.read_text(encoding="utf-8") == f"-m {PROBE_MODULE}\n"


def test_health_check_runs_the_real_probe_against_the_snapshot(
    tmp_path: Path,
) -> None:
    state_dir = tmp_path / "state"
    harness = _write_harness(tmp_path, sys.executable)
    env = {
        "PYTHONPATH": str(REPO_ROOT),
        "PYTMBOT_STATE_DIR": str(state_dir),
        # As in the Docker image: enables inspect mode, which used to print a
        # SystemExit traceback and turn exit code 2 into 1.
        "PYTHONINSPECT": "0",
    }

    missing = _run_harness(harness, env)
    assert missing.returncode == 1
    assert "no health data yet" in missing.stdout
    assert "pytmbot health check: no health snapshot" in missing.stderr
    assert "Traceback" not in missing.stderr

    writer = HealthSnapshotWriter(state_dir / "health.json")
    # This test process stands in for the running bot.
    writer.write(
        overall="healthy",
        healthy=True,
        components={"telegram_api": "healthy"},
        interval_seconds=120.0,
    )
    healthy = _run_harness(harness, env)
    assert healthy.returncode == 0, healthy.stdout + healthy.stderr
    assert "Health check passed" in healthy.stdout

    writer.write(
        overall="unhealthy",
        healthy=False,
        components={"telegram_api": "unhealthy"},
        interval_seconds=120.0,
    )
    unhealthy = _run_harness(harness, env)
    assert unhealthy.returncode == 1
    assert "bot is unhealthy" in unhealthy.stdout
    assert "telegram_api=unhealthy" in unhealthy.stderr
