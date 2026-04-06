from __future__ import annotations

import importlib
import sys
from types import ModuleType, SimpleNamespace

import pytest

from pytmbot.exceptions import InitializationError
from tests._main_module_loader import load_main_module


def _load_main_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    return load_main_module(monkeypatch, argv0="pytmbot-main-test")


def test_launcher_normalize_mode_and_log_level_logic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_module = _load_main_module(monkeypatch)
    launcher = main_module.BotLauncher()

    assert launcher._normalize_mode_value(SimpleNamespace(value="dev")) == "dev"
    assert launcher._determine_health_log_level("healthy", True, False, True) == "info"
    assert (
        launcher._determine_health_log_level("degraded", False, True, False)
        == "warning"
    )
    assert (
        launcher._determine_health_log_level("critical", False, False, False) == "error"
    )


def test_should_log_health_status_reacts_to_state_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_module = _load_main_module(monkeypatch)
    launcher = main_module.BotLauncher()
    launcher._health_manager = SimpleNamespace(
        get_summary=lambda: {"overall": "healthy"},
    )

    assert launcher._should_log_health_status() is True
    launcher._previous_health_level = "healthy"
    launcher._last_health_log = 10_000_000_000.0
    assert launcher._should_log_health_status() is False


def test_validate_environment_raises_for_old_python(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_module = _load_main_module(monkeypatch)
    launcher = main_module.BotLauncher()
    monkeypatch.setattr(main_module.sys, "version_info", (3, 9, 0))
    with pytest.raises(InitializationError):
        launcher.validate_environment()


def test_start_bot_polling_sets_shutdown_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_module = _load_main_module(monkeypatch)
    launcher = main_module.BotLauncher()
    launcher.bot = None

    fake_telebot = SimpleNamespace(remove_webhook=lambda: None)
    launcher._start_bot_polling(fake_telebot)
    assert launcher.shutdown_requested.is_set() is True


@pytest.mark.parametrize(
    ("health_result", "expected_exit_code"),
    [(True, 0), (False, 1), (None, 2)],
)
def test_check_health_exit_codes(
    monkeypatch: pytest.MonkeyPatch,
    health_result: bool | None,
    expected_exit_code: int,
) -> None:
    main_module = _load_main_module(monkeypatch)

    class _FakeHealthStatus:
        def __init__(self, result: bool | None) -> None:
            self.last_health_check_result = result

    monkeypatch.setattr(
        main_module, "HealthStatus", lambda: _FakeHealthStatus(health_result)
    )
    with pytest.raises(SystemExit) as exc_info:
        main_module.check_health()
    assert exc_info.value.code == expected_exit_code


def test_module_entrypoint_invokes_main(monkeypatch: pytest.MonkeyPatch) -> None:
    main_module = _load_main_module(monkeypatch)
    calls = {"count": 0}

    monkeypatch.setattr(
        main_module, "main", lambda: calls.__setitem__("count", calls["count"] + 1)
    )
    sys.modules.pop("pytmbot.__main__", None)

    importlib.import_module("pytmbot.__main__")

    assert calls["count"] == 1
