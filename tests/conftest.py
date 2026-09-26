from __future__ import annotations

import os
import sys
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest
from telebot.types import InputRichMessage

from pytmbot.utils.cli import parse_cli_args
from pytmbot.utils.environment import get_environment_state, is_running_in_docker
from pytmbot.utils.rich_html import find_rich_html_issues


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


@pytest.fixture(autouse=True)
def validate_rich_html(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail any test that builds rich HTML Telegram would render incorrectly."""
    original_init = InputRichMessage.__init__

    def checked_init(
        self: InputRichMessage, html: str | None = None, *args: Any, **kwargs: Any
    ) -> None:
        if html is not None:
            issues = find_rich_html_issues(html)
            assert not issues, f"Invalid rich HTML: {issues}\n{html}"
        original_init(self, html, *args, **kwargs)

    monkeypatch.setattr(InputRichMessage, "__init__", checked_init)
