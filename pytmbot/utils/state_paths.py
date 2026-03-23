#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

from __future__ import annotations

import os
from pathlib import Path

_APP_STATE_DIR = "pytmbot"


def get_state_root_path() -> Path:
    """Return the per-user state root for runtime files."""
    if override_dir := os.environ.get("PYTMBOT_STATE_DIR"):
        return Path(override_dir).expanduser()

    if xdg_state_home := os.environ.get("XDG_STATE_HOME"):
        return Path(xdg_state_home).expanduser() / _APP_STATE_DIR

    return Path.home() / ".local" / "state" / _APP_STATE_DIR


def ensure_private_directory(path: Path) -> Path:
    """Create a private runtime directory when possible."""
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path
