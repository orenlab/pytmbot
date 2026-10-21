from __future__ import annotations

import importlib
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from pytmbot.exceptions import InitializationError
from pytmbot.health_system.snapshot import HealthSnapshotWriter
from pytmbot.utils.cli import parse_cli_args
from pytmbot.utils.state_paths import StateRoot, StateRootSource
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


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            StateRootSource.RUNTIME_FALLBACK,
            [("bot.launcher.state.dir.fallback.info", {"state_dir": "/dev/shm/x"})],
        ),
        (StateRootSource.DEFAULT, []),
    ],
)
def test_validate_environment_reports_runtime_state_fallback(
    monkeypatch: pytest.MonkeyPatch,
    source: StateRootSource,
    expected: list[tuple[str, dict[str, object]]],
) -> None:
    main_module = _load_main_module(monkeypatch)
    launcher = main_module.BotLauncher()
    monkeypatch.setattr(
        main_module, "resolve_state_root", lambda: StateRoot(Path("/dev/shm/x"), source)
    )
    infos: list[tuple[str, dict[str, object]]] = []

    @contextmanager
    def capture_log_context(**context: object) -> Iterator[SimpleNamespace]:
        yield SimpleNamespace(
            debug=lambda _message: None,
            info=lambda message: infos.append((message, context)),
        )

    monkeypatch.setattr(launcher, "log_context", capture_log_context)

    launcher.validate_environment()

    assert infos == expected


def test_start_bot_polling_sets_shutdown_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_module = _load_main_module(monkeypatch)
    launcher = main_module.BotLauncher()
    launcher.bot = None

    fake_telebot = SimpleNamespace(remove_webhook=lambda: None)
    launcher._start_bot_polling(fake_telebot)
    assert launcher.shutdown_requested.is_set() is True


@pytest.mark.parametrize("probe_exit_code", [0, 1, 2])
def test_check_health_exits_with_snapshot_probe_code(
    monkeypatch: pytest.MonkeyPatch,
    probe_exit_code: int,
) -> None:
    main_module = _load_main_module(monkeypatch)
    monkeypatch.setattr(main_module, "run_probe", lambda: probe_exit_code)

    with pytest.raises(SystemExit) as exc_info:
        main_module.check_health()
    assert exc_info.value.code == probe_exit_code


def test_check_health_reads_snapshot_not_in_process_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    main_module = _load_main_module(monkeypatch)
    monkeypatch.setenv("PYTMBOT_STATE_DIR", str(tmp_path))

    with pytest.raises(SystemExit) as exc_info:
        main_module.check_health()

    assert exc_info.value.code == 2
    assert "no health snapshot" in capsys.readouterr().err


def test_setup_health_system_wires_run_mode_and_snapshot_writer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    main_module = _load_main_module(monkeypatch)
    monkeypatch.setenv("PYTMBOT_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(sys, "argv", ["pytmbot-main-test", "--webhook", "true"])
    monkeypatch.setattr(main_module, "args", None)
    parse_cli_args.cache_clear()
    captured: dict[str, object] = {}

    def _fake_create_health_manager(**kwargs: object) -> SimpleNamespace:
        captured.update(kwargs)
        return SimpleNamespace(monitor=SimpleNamespace(checker_count=0))

    class _HealthStatusStub:
        def set_manager(self, _manager: SimpleNamespace) -> None:
            return

    monkeypatch.setattr(
        main_module, "create_health_manager", _fake_create_health_manager
    )
    # Keep the fake manager out of the process-wide HealthStatus singleton.
    monkeypatch.setattr(main_module, "HealthStatus", _HealthStatusStub)
    launcher = main_module.BotLauncher()
    launcher.bot = SimpleNamespace(bot=SimpleNamespace())

    launcher.setup_health_system()

    assert captured["webhook_mode"] is True
    writer = captured["snapshot_writer"]
    assert isinstance(writer, HealthSnapshotWriter)
    assert writer.path == tmp_path / "health.json"


def test_module_entrypoint_invokes_main(monkeypatch: pytest.MonkeyPatch) -> None:
    main_module = _load_main_module(monkeypatch)
    calls = {"count": 0}

    monkeypatch.setattr(
        main_module, "main", lambda: calls.__setitem__("count", calls["count"] + 1)
    )
    sys.modules.pop("pytmbot.__main__", None)

    importlib.import_module("pytmbot.__main__")

    assert calls["count"] == 1
