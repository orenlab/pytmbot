#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import errno
import os
import stat
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

_APP_STATE_DIR = "pytmbot"
# Writable in every Docker container, a read-only root filesystem included. Only a real
# directory owned by the bot user and closed to others is used there (_is_usable_fallback,
# ensure_private_directory), so another user of the shared directory cannot plant it.
_RUNTIME_FALLBACK_BASE = Path("/dev/shm")  # NOSONAR
_PRIVATE_DIRECTORY_MODE = 0o700


class StateRootSource(StrEnum):
    """Where the state root comes from."""

    STATE_DIR_ENV = "PYTMBOT_STATE_DIR"
    XDG_STATE_HOME = "XDG_STATE_HOME"
    DEFAULT = "default"
    RUNTIME_FALLBACK = "runtime_fallback"


@dataclass(frozen=True, slots=True)
class StateRoot:
    path: Path
    source: StateRootSource


def resolve_state_root() -> StateRoot:
    """
    Return the per-user state root for runtime files and where it comes from.

    An explicit ``PYTMBOT_STATE_DIR`` or ``XDG_STATE_HOME`` is used as is. When the
    default ``~/.local/state/pytmbot`` cannot be written (a read-only root filesystem
    without ``PYTMBOT_STATE_DIR``), a private directory in ``/dev/shm`` is used
    instead. The choice only depends on the filesystem, so the bot and the health
    probe, which run as the same user in the same container, resolve the same path.
    """
    if override_dir := os.environ.get("PYTMBOT_STATE_DIR"):
        return StateRoot(Path(override_dir).expanduser(), StateRootSource.STATE_DIR_ENV)

    if xdg_state_home := os.environ.get("XDG_STATE_HOME"):
        return StateRoot(
            Path(xdg_state_home).expanduser() / _APP_STATE_DIR,
            StateRootSource.XDG_STATE_HOME,
        )

    default_dir = Path.home() / ".local" / "state" / _APP_STATE_DIR
    if not _can_write_directory(default_dir):
        fallback_dir = _RUNTIME_FALLBACK_BASE / f"{_APP_STATE_DIR}-{os.geteuid()}"
        if _is_usable_fallback(fallback_dir):
            return StateRoot(fallback_dir, StateRootSource.RUNTIME_FALLBACK)
    return StateRoot(default_dir, StateRootSource.DEFAULT)


def get_state_root_path() -> Path:
    """Return the per-user state root for runtime files."""
    return resolve_state_root().path


def ensure_private_directory(path: Path) -> Path:
    """
    Create a private runtime directory when possible.

    Inside a shared sticky directory such as ``/tmp`` or ``/dev/shm`` another user
    may have created ``path`` first, so there it must be our own private directory;
    ``PermissionError`` is raised otherwise.
    """
    path.mkdir(mode=_PRIVATE_DIRECTORY_MODE, parents=True, exist_ok=True)
    try:
        os.chmod(path, _PRIVATE_DIRECTORY_MODE)
    except OSError:
        pass
    if _is_shared_sticky_directory(path.parent) and not _is_private_directory(path):
        raise PermissionError(
            errno.EPERM,
            "not a private directory owned by the bot user",
            os.fspath(path),
        )
    return path


def _can_write_directory(path: Path) -> bool:
    """Return whether ``path`` is a writable directory or could be created as one."""
    candidate = path
    while not os.path.lexists(candidate):
        if candidate.parent == candidate:
            return False
        candidate = candidate.parent
    # access() also reports a read-only filesystem (EROFS).
    return candidate.is_dir() and os.access(candidate, os.W_OK | os.X_OK)


def _is_usable_fallback(path: Path) -> bool:
    """Return whether the runtime fallback can be used (never someone else's)."""
    if os.path.lexists(path):
        return _is_private_directory(path) and os.access(path, os.W_OK | os.X_OK)
    base = path.parent
    return base.is_dir() and os.access(base, os.W_OK | os.X_OK)


def _is_private_directory(path: Path) -> bool:
    """Return whether ``path`` is a real directory owned by us and closed to others."""
    try:
        status = os.lstat(path)
    except OSError:
        return False
    return (
        stat.S_ISDIR(status.st_mode)
        and status.st_uid == os.geteuid()
        and not status.st_mode & 0o077
    )


def _is_shared_sticky_directory(path: Path) -> bool:
    try:
        mode = os.stat(path).st_mode
    except OSError:
        return False
    return bool(mode & stat.S_ISVTX and mode & stat.S_IWOTH)
