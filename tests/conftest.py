from __future__ import annotations

import os
import sys
from collections.abc import Generator
from pathlib import Path

import pytest

from pytmbot.utils.cli import parse_cli_args
from pytmbot.utils.environment import get_environment_state, is_running_in_docker


def pytest_sessionstart(session: pytest.Session) -> None:
    """Normalize argv before test collection imports application modules."""
    del session
    sys.argv[:] = ["pytmbot-test"]
    sample_config_path = Path(__file__).resolve().parents[1] / "pytmbot.yaml.sample"
    os.environ["PYTMBOT_CONFIG_PATH"] = str(sample_config_path)


@pytest.fixture(autouse=True)
def stable_process_state(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[None, None, None]:
    """Keep process-wide caches and argv deterministic across tests."""
    monkeypatch.setattr(sys, "argv", ["pytmbot-test"])
    parse_cli_args.cache_clear()
    is_running_in_docker.cache_clear()
    get_environment_state.cache_clear()
    yield
    parse_cli_args.cache_clear()
    is_running_in_docker.cache_clear()
    get_environment_state.cache_clear()
