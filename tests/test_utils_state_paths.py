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
from pytmbot.webhook import RateLimit


@pytest.fixture
def shm_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A sticky, world-writable stand-in for a container's private /dev/shm."""
    directory = tmp_path / "shm"
    directory.mkdir()
    directory.chmod(0o1777)
    monkeypatch.setattr(state_paths, "_RUNTIME_FALLBACK_BASE", directory)
    monkeypatch.setattr(state_paths, "_has_private_ipc_namespace", lambda: True)
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


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.lstat(path).st_mode)


def test_explicit_state_dir_is_used_as_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, unwritable_home: Path
) -> None:
    configured = tmp_path / "missing" / "state"
    monkeypatch.setenv("PYTMBOT_STATE_DIR", str(configured))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "xdg"))

    state_root = resolve_state_root()

    assert state_root.path == configured
    assert state_root.source is StateRootSource.STATE_DIR_ENV
    assert state_root.writable is True


def test_unwritable_explicit_state_dir_never_falls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    shm_dir: Path,
    unwritable_home: Path,
) -> None:
    configured = unwritable_home / "state"
    monkeypatch.setenv("PYTMBOT_STATE_DIR", str(configured))

    state_root = resolve_state_root()

    assert state_root.path == configured
    assert state_root.source is StateRootSource.STATE_DIR_ENV
    assert state_root.writable is False
    assert not _fallback_dir(shm_dir).exists()


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
    assert state_root.writable is True
    assert get_state_root_path() == state_root.path


def test_unwritable_home_falls_back_to_runtime_directory(
    shm_dir: Path, unwritable_home: Path
) -> None:
    state_root = resolve_state_root()

    assert state_root.path == _fallback_dir(shm_dir)
    assert state_root.source is StateRootSource.RUNTIME_FALLBACK
    assert state_root.writable is True


def _assert_no_fallback(unwritable_home: Path) -> None:
    state_root = resolve_state_root()
    assert state_root.source is StateRootSource.DEFAULT
    assert state_root.path == unwritable_home / ".local" / "state" / "pytmbot"
    assert state_root.writable is False


def test_host_ipc_namespace_disables_the_fallback(
    monkeypatch: pytest.MonkeyPatch, shm_dir: Path, unwritable_home: Path
) -> None:
    monkeypatch.setattr(state_paths, "_has_private_ipc_namespace", lambda: False)

    _assert_no_fallback(unwritable_home)


def test_missing_runtime_directory_disables_the_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    shm_dir: Path,
    unwritable_home: Path,
) -> None:
    monkeypatch.setattr(state_paths, "_RUNTIME_FALLBACK_BASE", tmp_path / "no-shm")

    _assert_no_fallback(unwritable_home)


def test_unshared_runtime_directory_disables_the_fallback(
    shm_dir: Path, unwritable_home: Path
) -> None:
    shm_dir.chmod(0o755)

    _assert_no_fallback(unwritable_home)


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

    _assert_no_fallback(unwritable_home)


def test_fallback_owned_by_another_user_is_not_trusted(
    monkeypatch: pytest.MonkeyPatch, shm_dir: Path, unwritable_home: Path
) -> None:
    other_uid = os.geteuid() + 1
    (shm_dir / f"pytmbot-{other_uid}").mkdir(mode=0o700)
    monkeypatch.setattr(os, "geteuid", lambda: other_uid)

    _assert_no_fallback(unwritable_home)


def test_fallback_symlink_is_not_trusted(
    tmp_path: Path, shm_dir: Path, unwritable_home: Path
) -> None:
    target = tmp_path / "elsewhere"
    target.mkdir(mode=0o700)
    _fallback_dir(shm_dir).symlink_to(target, target_is_directory=True)

    _assert_no_fallback(unwritable_home)


@pytest.mark.skipif(
    not os.path.exists("/proc/self/ns/ipc"), reason="needs Linux IPC namespaces"
)
def test_ipc_namespace_check_recognises_the_host_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    own_inode = os.stat("/proc/self/ns/ipc").st_ino

    monkeypatch.setattr(state_paths, "_HOST_IPC_NAMESPACE_INODE", own_inode)
    assert state_paths._has_private_ipc_namespace() is False

    monkeypatch.setattr(state_paths, "_HOST_IPC_NAMESPACE_INODE", own_inode + 1)
    assert state_paths._has_private_ipc_namespace() is True

    monkeypatch.setattr(state_paths, "_IPC_NAMESPACE_PATH", "/nonexistent/ns/ipc")
    assert state_paths._has_private_ipc_namespace() is False


def test_ensure_private_directory_creates_private_parents(tmp_path: Path) -> None:
    directory = ensure_private_directory(tmp_path / "a" / "b")

    assert directory.is_dir()
    assert _mode(tmp_path / "a") == 0o700
    assert _mode(directory) == 0o700


def test_ensure_private_directory_tightens_own_directory_in_shared_dir(
    shm_dir: Path,
) -> None:
    directory = shm_dir / "state"
    directory.mkdir()
    directory.chmod(0o777)

    ensure_private_directory(directory)

    assert _mode(directory) == 0o700


def test_ensure_private_directory_rejects_symlink_in_shared_dir(
    tmp_path: Path, shm_dir: Path
) -> None:
    target = tmp_path / "elsewhere"
    target.mkdir(mode=0o755)
    link = shm_dir / "state"
    link.symlink_to(target, target_is_directory=True)

    with pytest.raises(PermissionError):
        ensure_private_directory(link)
    # The check comes first: the symlink target was not touched.
    assert _mode(target) == 0o755


def test_ensure_private_directory_rejects_file_in_shared_dir(shm_dir: Path) -> None:
    planted = shm_dir / "state"
    planted.write_text("", encoding="utf-8")

    with pytest.raises(PermissionError):
        ensure_private_directory(planted)


def test_ensure_private_directory_rejects_foreign_directory_in_shared_dir(
    monkeypatch: pytest.MonkeyPatch, shm_dir: Path
) -> None:
    directory = shm_dir / "state"
    directory.mkdir(mode=0o777)
    other_uid = os.stat(directory).st_uid + 1
    monkeypatch.setattr(os, "geteuid", lambda: other_uid)

    with pytest.raises(PermissionError):
        ensure_private_directory(directory)
    assert stat.S_IMODE(os.stat(directory).st_mode) != 0o700


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
    assert _mode(writer.path.parent) == 0o700
    assert _mode(writer.path) == 0o600
    assert evaluate_health_snapshot().status is ProbeStatus.HEALTHY


def test_webhook_ban_state_uses_private_directories(
    shm_dir: Path, unwritable_home: Path
) -> None:
    state_dir = get_state_root_path() / "webhook_ratelimit" / "8443"

    limiter = RateLimit(limit=1, period=10, state_file=str(state_dir / "main.json"))

    assert limiter._state_file == str(state_dir / "main.json")
    for directory in (_fallback_dir(shm_dir), state_dir.parent, state_dir):
        assert _mode(directory) == 0o700


def test_webhook_ban_state_is_disabled_for_a_planted_directory(
    tmp_path: Path, shm_dir: Path
) -> None:
    target = tmp_path / "elsewhere"
    target.mkdir()
    (shm_dir / "state").symlink_to(target, target_is_directory=True)

    limiter = RateLimit(
        limit=1, period=10, state_file=str(shm_dir / "state" / "main.json")
    )

    assert limiter._state_file is None
