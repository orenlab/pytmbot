from __future__ import annotations

import importlib
import sys
from types import ModuleType

import pytest

from pytmbot.utils.cli import parse_cli_args


def load_main_module(
    monkeypatch: pytest.MonkeyPatch,
    *,
    argv0: str,
) -> ModuleType:
    """Reload ``pytmbot.main`` with a controlled argv for tests."""
    parse_cli_args.cache_clear()
    monkeypatch.setattr(sys, "argv", [argv0])
    import pytmbot.main as main_module

    return importlib.reload(main_module)
