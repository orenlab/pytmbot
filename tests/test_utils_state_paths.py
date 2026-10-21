from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from pytmbot.health_system.snapshot import (
    HealthSnapshotWriter,
    ProbeStatus,
    evaluate_health_snapshot,
)
from pytmbot.utils import state_paths
from pytmbot.utils.state_paths import (
    StateRootSource,
    ensure_private_directory,
    get_state_root_path,
    resolve_state_root,
)


@pytest.fixture
def shm_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A sticky, world-writable stand-in for /dev/shm."""
    directory = tmp_path / "shm"
    directory.mkdir()
    directory.chmod(0o1777)
    monkeypatch.setattr(state_paths, "_RUNTIME_FALLBACK_BASE", directory)
    monkeypatch.delenv("PYTMBOT_STATE_DIR", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    return directory


@pytest.fixture
def unwritable_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A home whose ~/.local/state cannot be created (works as root too)."""
    home = tmp_path / "home-is-a-file"
    home.write_text("", encoding="utf-8")
    monkeypatch.setenv("HOME", str(home))
    return home


def _fallback_dir(shm_dir: Path) -> Path:
    return shm_dir / f"pytmbot-{os.geteuid()}"


def test_explicit_state_dir_is_used_as_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unwritable_home: Path
) -> None:
    configured = tmp_path / "missing" / "state"
    monkeypatch.setenv("PYTMBOT_STATE_DIR", str(configured))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))

    state_root = resolve_state_root()

    assert state_root.path == configured
    assert state_root.source is StateRootSource.STATE_DIR_ENV


def test_xdg_state_home_is_used_without_state_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shm_dir: Path
) -> None:
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))

    state_root = resolve_state_root()

    assert state_root.path == tmp_path / "xdg" / "pytmbot"
    assert state_root.source is StateRootSource.XDG_STATE_HOME


def test_writable_home_keeps_the_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shm_dir: Path
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    state_root = resolve_state_root()

    assert state_root.path == tmp_path / ".local" / "state" / "pytmbot"
    assert state_root.source is StateRootSource.DEFAULT
    assert get_state_root_path() == state_root.path


def test_unwritable_home_falls_back_to_runtime_directory(
    shm_dir: Path, unwritable_home: Path
) -> None:
    state_root = resolve_state_root()

    assert state_root.path == _fallback_dir(shm_dir)
    assert state_root.source is StateRootSource.RUNTIME_FALLBACK


def test_missing_runtime_directory_keeps_the_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unwritable_home: Path
) -> None:
    monkeypatch.setattr(state_paths, "_RUNTIME_FALLBACK_BASE", tmp_path / "no-shm")
    monkeypatch.delenv("PYTMBOT_STATE_DIR", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)

    state_root = resolve_state_root()

    assert state_root.source is StateRootSource.DEFAULT
    assert state_root.path == unwritable_home / ".local" / "state" / "pytmbot"


def test_existing_private_fallback_is_reused(
    shm_dir: Path, unwritable_home: Path
) -> None:
    fallback = _fallback_dir(shm_dir)
    fallback.mkdir(mode=0o700)

    assert resolve_state_root().path == fallback


@pytest.mark.parametrize("mode", [0o755, 0o770, 0o777])
def test_fallback_open_to_others_is_not_trusted(
    shm_dir: Path, unwritable_home: Path, mode: int
) -> None:
    fallback = _fallback_dir(shm_dir)
    fallback.mkdir()
    fallback.chmod(mode)

    assert resolve_state_root().source is StateRootSource.DEFAULT


def test_fallback_symlink_is_not_trusted(
    tmp_path: Path, shm_dir: Path, unwritable_home: Path
) -> None:
    target = tmp_path / "elsewhere"
    target.mkdir(mode=0o700)
    _fallback_dir(shm_dir).symlink_to(target, target_is_directory=True)

    assert resolve_state_root().source is StateRootSource.DEFAULT


def test_ensure_private_directory_creates_private_directory(tmp_path: Path) -> None:
    directory = ensure_private_directory(tmp_path / "a" / "b")

    assert directory.is_dir()
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700


def test_ensure_private_directory_tightens_own_directory_in_shared_dir(
    shm_dir: Path,
) -> None:
    directory = shm_dir / "state"
    directory.mkdir()
    directory.chmod(0o777)

    ensure_private_directory(directory)

    assert stat.S_IMODE(directory.stat().st_mode) == 0o700


def test_ensure_private_directory_rejects_symlink_in_shared_dir(
    tmp_path: Path, shm_dir: Path
) -> None:
    target = tmp_path / "elsewhere"
    target.mkdir(mode=0o700)
    link = shm_dir / "state"
    link.symlink_to(target, target_is_directory=True)

    with pytest.raises(PermissionError):
        ensure_private_directory(link)


def test_bot_and_probe_agree_on_the_fallback(
    shm_dir: Path, unwritable_home: Path
) -> None:
    writer = HealthSnapshotWriter()
    writer.write(
        overall="healthy",
        healthy=True,
        components={"polling": "healthy"},
        interval_seconds=120.0,
    )

    assert writer.path.parent == _fallback_dir(shm_dir)
    assert stat.S_IMODE(writer.path.parent.stat().st_mode) == 0o700
    assert evaluate_health_snapshot().status is ProbeStatus.HEALTHY
