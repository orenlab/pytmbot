from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ENTRYPOINT = REPO_ROOT / "entrypoint.sh"
CHECK_MODULE = "pytmbot.adapters.docker.check"

pytestmark = pytest.mark.skipif(
    shutil.which("sh") is None, reason="POSIX sh is required"
)

# Stands in for the image's Python: records its arguments and exits with $STUB_RC.
_STUB_PYTHON = """#!/bin/sh
printf '%s\\n' "$*" >> "$STUB_CALLS"
exit "$STUB_RC"
"""


def _entrypoint_with_stub(tmp_path: Path) -> Path:
    stub = tmp_path / "python3"
    stub.write_text(_STUB_PYTHON, encoding="utf-8")
    stub.chmod(0o755)
    script = ENTRYPOINT.read_text(encoding="utf-8")
    original = 'PYTHON_PATH="/opt/venv/bin/python3"\n'
    assert script.count(original) == 1
    entrypoint = tmp_path / "entrypoint.sh"
    entrypoint.write_text(
        script.replace(original, f'PYTHON_PATH="{stub}"\n'), encoding="utf-8"
    )
    return entrypoint


def _check_docker(tmp_path: Path, stub_rc: int) -> tuple[int, list[str]]:
    calls = tmp_path / "calls.log"
    result = subprocess.run(
        ["sh", str(_entrypoint_with_stub(tmp_path)), "--check-docker"],
        cwd=REPO_ROOT,
        env={**os.environ, "STUB_RC": str(stub_rc), "STUB_CALLS": str(calls)},
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    recorded = calls.read_text(encoding="utf-8").splitlines() if calls.exists() else []
    return result.returncode, recorded


@pytest.mark.parametrize(("stub_rc", "expected"), [(0, 0), (1, 1), (3, 1)])
def test_check_docker_exit_code_follows_the_docker_api_check(
    tmp_path: Path, stub_rc: int, expected: int
) -> None:
    returncode, calls = _check_docker(tmp_path, stub_rc)

    assert returncode == expected
    assert calls == [f"-m {CHECK_MODULE}"]
