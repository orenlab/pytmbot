#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

# Runtime state root: the health snapshot, TOTP replay markers and webhook bans.
# Everything kept there may be lost on restart (tokens and settings never go there).

from __future__ import annotations

import errno
import os
import stat
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

_APP_STATE_DIR = "pytmbot"
# Docker mounts a tmpfs here in every container, a read-only root filesystem included,
# private to the container's IPC namespace. Only a real directory owned by the bot user
# and closed to others is used there (see _is_usable_fallback, ensure_private_directory).
_RUNTIME_FALLBACK_BASE = Path("/dev/shm")  # NOSONAR  # nosec B108
# The kernel gives the host's (initial) IPC namespace this fixed inode (PROC_IPC_INIT_INO);
# there /dev/shm is shared with the host, e.g. with `--ipc=host` or outside a container.
_HOST_IPC_NAMESPACE_INODE = 0xEFFFFFFF
_IPC_NAMESPACE_PATH = "/proc/self/ns/ipc"
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
    # Whether the directory exists as a writable directory or can be created.
    writable: bool = True


def resolve_state_root() -> StateRoot:
    """
    Return the per-user state root for runtime files and where it comes from.

    An explicit ``PYTMBOT_STATE_DIR`` or ``XDG_STATE_HOME`` is used as is, writable or
    not. When the default ``~/.local/state/pytmbot`` cannot be written (a read-only
    root filesystem without ``PYTMBOT_STATE_DIR``), a private directory in the
    container's ``/dev/shm`` is used instead. The choice only depends on the
    filesystem, so the bot and the health probe, which run as the same user in the
    same container, resolve the same path.
    """
    if override_dir := os.environ.get("PYTMBOT_STATE_DIR"):
        return _explicit_root(
            Path(override_dir).expanduser(), StateRootSource.STATE_DIR_ENV
        )

    if xdg_state_home := os.environ.get("XDG_STATE_HOME"):
        return _explicit_root(
            Path(xdg_state_home).expanduser() / _APP_STATE_DIR,
            StateRootSource.XDG_STATE_HOME,
        )

    default_dir = Path.home() / ".local" / "state" / _APP_STATE_DIR
    if _can_write_directory(default_dir):
        return StateRoot(default_dir, StateRootSource.DEFAULT)

    fallback_dir = _RUNTIME_FALLBACK_BASE / f"{_APP_STATE_DIR}-{os.geteuid()}"
    if _has_private_ipc_namespace() and _is_usable_fallback(fallback_dir):
        return StateRoot(fallback_dir, StateRootSource.RUNTIME_FALLBACK)
    return StateRoot(default_dir, StateRootSource.DEFAULT, writable=False)


def get_state_root_path() -> Path:
    """Return the per-user state root for runtime files."""
    return resolve_state_root().path


def ensure_private_directory(path: Path) -> Path:
    """
    Create ``path`` and its missing parents as directories closed to other users.

    Inside a shared sticky directory such as ``/dev/shm`` or ``/tmp`` another user may
    have created ``path`` first, so there it must be a real directory owned by the
    bot user; ``PermissionError`` is raised otherwise. The sticky bit then keeps
    other users from renaming or replacing it.
    """
    parent = path.parent
    if parent != path and not os.path.isdir(parent):
        ensure_private_directory(parent)
    try:
        os.mkdir(path, _PRIVATE_DIRECTORY_MODE)
    except FileExistsError:
        pass

    if _is_shared_sticky_directory(parent):
        _claim_private_directory(path)
    else:
        try:
            os.chmod(path, _PRIVATE_DIRECTORY_MODE)
        except OSError:
            pass
    return path


def _explicit_root(path: Path, source: StateRootSource) -> StateRoot:
    return StateRoot(path, source, writable=_can_write_directory(path))


def _claim_private_directory(path: Path) -> None:
    """Verify ``path`` is our own real directory and close it to others."""
    try:
        # O_NOFOLLOW: a symlink is refused instead of followed.
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except OSError as error:
        raise PermissionError(
            errno.EPERM, "not a real directory", os.fspath(path)
        ) from error
    try:
        if os.fstat(descriptor).st_uid != os.geteuid():
            raise PermissionError(
                errno.EPERM, "directory is owned by another user", os.fspath(path)
            )
        os.fchmod(descriptor, _PRIVATE_DIRECTORY_MODE)
    finally:
        os.close(descriptor)


def _can_write_directory(path: Path) -> bool:
    """Return whether ``path`` is a writable directory or could be created as one."""
    candidate = path
    while not os.path.lexists(candidate):
        if candidate.parent == candidate:
            return False
        candidate = candidate.parent
    # access() also reports a read-only filesystem (EROFS).
    return os.path.isdir(candidate) and os.access(candidate, os.W_OK | os.X_OK)


def _has_private_ipc_namespace() -> bool:
    """Return whether /dev/shm belongs to this container rather than the host."""
    try:
        return os.stat(_IPC_NAMESPACE_PATH).st_ino != _HOST_IPC_NAMESPACE_INODE
    except OSError:
        return False


def _is_usable_fallback(path: Path) -> bool:
    """Return whether the runtime fallback can be used (never someone else's)."""
    if os.path.lexists(path):
        return _is_private_directory(path) and os.access(path, os.W_OK | os.X_OK)
    base = path.parent
    return (
        _is_shared_sticky_directory(base)
        and os.path.isdir(base)
        and os.access(base, os.W_OK | os.X_OK)
    )


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
