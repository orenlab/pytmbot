from __future__ import annotations

import importlib
import signal
import sys
from collections.abc import Callable, Generator
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace

import pytest

from pytmbot.exceptions import ShutdownError
from pytmbot.utils.cli import parse_cli_args


def _load_main_module(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    parse_cli_args.cache_clear()
    monkeypatch.setattr(sys, "argv", ["pytmbot-main-extra-test"])
    import pytmbot.main as main_module

    return importlib.reload(main_module)


def _install_run_main_loop_stubs(
    *,
    monkeypatch: pytest.MonkeyPatch,
    main_module: ModuleType,
    launcher: object,
    polling_alive: bool,
    should_log_health: Callable[[], bool] | None = None,
) -> None:
    bot_component = SimpleNamespace(
        initialize_bot_core=lambda: SimpleNamespace(remove_webhook=lambda: None),
        bot=SimpleNamespace(),
        get_bot_session_statistics=lambda: {},
    )

    @contextmanager
    def _managed() -> Generator[object, None, None]:
        yield bot_component

    class _ThreadStub:
        def __init__(
            self,
            *,
            target: Callable[..., object],
            args: tuple[object, ...],
            **kwargs: object,
        ) -> None:
            del kwargs
            self._target = target
            self._args = args
            self._alive = polling_alive

        def start(self) -> None:
            self._target(*self._args)
            if not polling_alive:
                self._alive = False

        def is_alive(self) -> bool:
            return self._alive

    monkeypatch.setattr(main_module.threading, "Thread", _ThreadStub)
    monkeypatch.setattr(main_module.time, "sleep", lambda _seconds: None)
    monkeypatch.setattr(launcher, "_managed_bot", _managed)
    monkeypatch.setattr(launcher, "setup_health_system", lambda: None)
    monkeypatch.setattr(launcher, "start_health_monitoring", lambda: None)
    monkeypatch.setattr(launcher, "_start_bot_polling", lambda _bot_instance: None)
    if should_log_health is not None:
        monkeypatch.setattr(launcher, "_should_log_health_status", should_log_health)


def test_register_cleanup_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    main_module = _load_main_module(monkeypatch)
    launcher = main_module.BotLauncher()
    calls: list[object] = []
    monkeypatch.setattr(main_module.atexit, "register", lambda fn: calls.append(fn))

    launcher._register_cleanup()
    launcher._register_cleanup()

    assert len(calls) == 1


def test_handle_sigint_graceful_then_forced(monkeypatch: pytest.MonkeyPatch) -> None:
    main_module = _load_main_module(monkeypatch)
    launcher = main_module.BotLauncher()
    kill_calls: list[tuple[int, int]] = []

    monkeypatch.setattr(
        main_module.os, "kill", lambda pid, sig: kill_calls.append((pid, sig))
    )
    monkeypatch.setattr(main_module.os, "getpid", lambda: 42)
    monkeypatch.setattr(main_module.signal, "signal", lambda _sig, _handler: None)
    monkeypatch.setattr(launcher, "_emergency_cleanup", lambda: None)

    launcher._handle_sigint("SIGINT")
    assert launcher.shutdown_requested.is_set() is True

    launcher._handle_sigint("SIGINT")
    assert kill_calls and kill_calls[0][0] == 42


def test_signal_handler_non_sigint_requests_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_module = _load_main_module(monkeypatch)
    launcher = main_module.BotLauncher()
    launcher._signal_handler(signal.SIGTERM, None)

    assert launcher.shutdown_requested.is_set() is True


def test_setup_health_system_and_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    main_module = _load_main_module(monkeypatch)
    launcher = main_module.BotLauncher()
    launcher.bot = SimpleNamespace(bot=SimpleNamespace())

    manager = SimpleNamespace(
        _monitor=SimpleNamespace(_checkers=[1, 2, 3]),
        start=lambda base_interval: None,
        stop=lambda timeout: None,
        get_summary=lambda: {"overall": "healthy"},
    )

    class _HealthStatusStub:
        def set_manager(self, _manager: object) -> None:
            return

    monkeypatch.setattr(main_module, "create_health_manager", lambda **kwargs: manager)
    monkeypatch.setattr(main_module, "HealthStatus", _HealthStatusStub)
    monkeypatch.setattr(main_module.time, "sleep", lambda _seconds: None)

    launcher.setup_health_system()
    assert launcher._health_manager is manager

    launcher.start_health_monitoring()
    launcher._stop_health_system()


def test_should_log_health_status_on_state_change_and_interval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_module = _load_main_module(monkeypatch)
    launcher = main_module.BotLauncher()
    launcher._health_manager = SimpleNamespace(
        get_summary=lambda: {"overall": "healthy"}
    )

    monkeypatch.setattr(main_module.time, "time", lambda: 100.0)
    assert launcher._should_log_health_status() is True

    launcher._previous_health_level = "healthy"
    launcher._last_health_log = 100.0
    monkeypatch.setattr(main_module.time, "time", lambda: 120.0)
    assert launcher._should_log_health_status() is False

    monkeypatch.setattr(main_module.time, "time", lambda: 200.0)
    assert launcher._should_log_health_status() is True


def test_log_health_status_startup_then_regular(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_module = _load_main_module(monkeypatch)
    launcher = main_module.BotLauncher()
    launcher.bot = SimpleNamespace(
        get_bot_session_statistics=lambda: {
            "session_id": "abc",
            "mode": "dev",
            "rate_limit_stats": {"active_users": 1, "total_violations": 0},
        }
    )
    launcher._health_manager = SimpleNamespace(
        get_summary=lambda: {
            "overall": "healthy",
            "operational": 3,
            "total": 3,
            "health_ratio": 1.0,
            "duration_ms": 10.0,
            "components": {"polling": {"level": "healthy", "latency_ms": 1.0}},
        }
    )

    called = {"main": 0, "details": 0}
    monkeypatch.setattr(main_module, "naturaltime", lambda _dt: "now")
    monkeypatch.setattr(
        launcher,
        "_log_main_health_status",
        lambda *args, **kwargs: called.__setitem__("main", called["main"] + 1),
    )
    monkeypatch.setattr(
        launcher,
        "_log_health_details",
        lambda *args, **kwargs: called.__setitem__("details", called["details"] + 1),
    )

    launcher.log_health_status()
    # Startup completion branch returns before main/details logging.
    assert called["main"] == 0

    launcher._bot_fully_started = True
    launcher.log_health_status()
    assert called["main"] == 1


def test_log_health_details_for_problematic_components(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_module = _load_main_module(monkeypatch)
    launcher = main_module.BotLauncher()
    launcher._log = main_module.logs.Logger()

    summary = {
        "components": {
            "sessions": {"level": "degraded", "latency_ms": 5.0, "details": {"x": 1}},
            "system_resources": {
                "level": "critical",
                "details": {
                    "cpu_percent": 91.0,
                    "memory_percent": "95%",
                    "memory_rss": "1GiB",
                    "threads": 30,
                    "status": "busy",
                },
            },
        }
    }
    metrics = {"rate_limit_stats": {"active_users": 2, "total_violations": 1}}

    launcher._log_health_details(summary, metrics)


def test_cleanup_and_shutdown_error_wrapping(monkeypatch: pytest.MonkeyPatch) -> None:
    main_module = _load_main_module(monkeypatch)
    launcher = main_module.BotLauncher()
    launcher.bot = SimpleNamespace(
        bot=SimpleNamespace(stop_polling=lambda: None, remove_webhook=lambda: None)
    )
    launcher._health_manager = SimpleNamespace(
        stop=lambda timeout: (_ for _ in ()).throw(RuntimeError("fail"))
    )

    monkeypatch.setattr(
        launcher,
        "_stop_bot_operations",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(ShutdownError):
        launcher.shutdown()


def test_start_bot_polling_paths_and_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    main_module = _load_main_module(monkeypatch)
    launcher = main_module.BotLauncher()
    calls = {"webhook": 0, "polling": 0}

    launcher.bot = SimpleNamespace(
        _start_webhook_server=lambda: calls.__setitem__(
            "webhook", calls["webhook"] + 1
        ),
        _start_polling_loop=lambda _bot: calls.__setitem__(
            "polling", calls["polling"] + 1
        ),
    )
    bot_instance = SimpleNamespace(remove_webhook=lambda: None)

    monkeypatch.setattr(
        main_module, "args", SimpleNamespace(webhook="False", mode="dev")
    )
    launcher._start_bot_polling(bot_instance)
    assert calls["polling"] == 1

    monkeypatch.setattr(
        main_module, "args", SimpleNamespace(webhook="True", mode="dev")
    )
    launcher._start_bot_polling(bot_instance)
    assert calls["webhook"] == 1
    assert calls["polling"] == 1

    launcher.bot = SimpleNamespace(
        _start_webhook_server=lambda: (_ for _ in ()).throw(RuntimeError("fail")),
        _start_polling_loop=lambda _bot: calls.__setitem__(
            "polling", calls["polling"] + 1
        ),
    )
    launcher.shutdown_requested.clear()
    launcher._start_bot_polling(bot_instance)
    assert calls["polling"] == 2
    assert launcher.shutdown_requested.is_set() is False

    launcher.bot = None
    launcher._start_bot_polling(bot_instance)
    assert launcher.shutdown_requested.is_set() is True


def test_run_success_and_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    main_module = _load_main_module(monkeypatch)
    launcher = main_module.BotLauncher()

    monkeypatch.setattr(launcher, "_register_cleanup", lambda: None)
    monkeypatch.setattr(launcher, "_setup_signal_handlers", lambda: None)
    monkeypatch.setattr(launcher, "validate_environment", lambda: None)
    monkeypatch.setattr(launcher, "run_main_loop", lambda: None)
    monkeypatch.setattr(launcher, "shutdown", lambda: None)
    launcher.run()

    launcher2 = main_module.BotLauncher()
    monkeypatch.setattr(launcher2, "_register_cleanup", lambda: None)
    monkeypatch.setattr(launcher2, "_setup_signal_handlers", lambda: None)
    monkeypatch.setattr(
        launcher2,
        "validate_environment",
        lambda: (_ for _ in ()).throw(RuntimeError("bad")),
    )
    monkeypatch.setattr(
        main_module.sys, "exit", lambda code: (_ for _ in ()).throw(SystemExit(code))
    )

    with pytest.raises(SystemExit) as exit_err:
        launcher2.run()
    assert exit_err.value.code == 1


def test_run_main_loop_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    main_module = _load_main_module(monkeypatch)
    launcher = main_module.BotLauncher()

    _install_run_main_loop_stubs(
        monkeypatch=monkeypatch,
        main_module=main_module,
        launcher=launcher,
        polling_alive=False,
    )
    monkeypatch.setattr(launcher, "log_health_status", lambda: None)

    launcher.run_main_loop()


def test_run_main_loop_restarts_polling_and_stops_after_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_module = _load_main_module(monkeypatch)
    launcher = main_module.BotLauncher()

    _install_run_main_loop_stubs(
        monkeypatch=monkeypatch,
        main_module=main_module,
        launcher=launcher,
        polling_alive=False,
    )

    calls = {"polling": 0}
    monkeypatch.setattr(
        launcher,
        "_start_bot_polling",
        lambda _bot_instance: calls.__setitem__("polling", calls["polling"] + 1),
    )
    monkeypatch.setattr(launcher, "log_health_status", lambda: None)

    launcher.run_main_loop()

    assert launcher.shutdown_requested.is_set() is True
    assert calls["polling"] == launcher.POLLING_RESTART_MAX_ATTEMPTS + 1


def test_shutdown_bot_silently_and_cleanup_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_module = _load_main_module(monkeypatch)
    launcher = main_module.BotLauncher()
    calls: list[str] = []

    bot_ok = SimpleNamespace(
        stop_polling=lambda: calls.append("stop"),
        remove_webhook=lambda: calls.append("remove"),
    )
    launcher.bot = SimpleNamespace(bot=bot_ok)
    launcher._session_manager = SimpleNamespace(
        shutdown=lambda: calls.append("session")
    )
    launcher._shutdown_bot_silently(silent=False)
    assert calls == ["stop", "remove", "session"]

    launcher.bot = SimpleNamespace(
        bot=SimpleNamespace(
            stop_polling=lambda: (_ for _ in ()).throw(RuntimeError("stop failed")),
            remove_webhook=lambda: None,
        )
    )
    launcher._shutdown_bot_silently(silent=True)
    launcher._shutdown_bot_silently(silent=False)


def test_managed_bot_exception_always_cleans_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_module = _load_main_module(monkeypatch)
    launcher = main_module.BotLauncher()
    cleaned: list[bool] = []

    monkeypatch.setattr(launcher, "_cleanup_bot", lambda: cleaned.append(True))

    class _BrokenPyTMBot:
        def __init__(self) -> None:
            raise RuntimeError("cannot init")

    fake_module = ModuleType("pytmbot.pytmbot_instance")
    fake_module.PyTMBot = _BrokenPyTMBot  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pytmbot.pytmbot_instance", fake_module)

    with pytest.raises(RuntimeError):
        with launcher._managed_bot():
            pass
    assert cleaned == [True]


def test_setup_and_start_health_system_error_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_module = _load_main_module(monkeypatch)
    launcher = main_module.BotLauncher()

    launcher.bot = None
    launcher.setup_health_system()

    launcher.bot = SimpleNamespace(bot=SimpleNamespace())
    monkeypatch.setattr(
        main_module,
        "create_health_manager",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("health init failed")),
    )
    launcher.setup_health_system()

    launcher._health_manager = None
    launcher.start_health_monitoring()

    launcher._health_manager = SimpleNamespace(
        start=lambda base_interval: (_ for _ in ()).throw(RuntimeError("start fail"))
    )
    launcher.start_health_monitoring()


def test_log_main_health_status_and_detail_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_module = _load_main_module(monkeypatch)
    launcher = main_module.BotLauncher()

    health_summary = {
        "overall": "critical",
        "operational": 1,
        "total": 4,
        "health_ratio": 0.25,
        "duration_ms": 77.0,
        "components": {
            "telegram_api": {"level": "critical", "latency_ms": 321.0},
            "polling": {"level": "degraded", "latency_ms": 0.0},
            "sessions": {"level": "degraded", "details": {"total_sessions": 3}},
            "system_resources": {
                "level": "critical",
                "details": {
                    "memory_percent": "95%",
                    "cpu_percent": 88.2,
                    "memory_rss": "512MiB",
                    "threads": 22,
                    "status": "stressed",
                },
            },
        },
    }

    launcher._log_main_health_status("critical", health_summary, "now", "error")
    launcher._log_health_details(
        health_summary, {"rate_limit_stats": {"active_users": 2, "total_violations": 1}}
    )


def test_cleanup_shutdown_and_signal_registration_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_module = _load_main_module(monkeypatch)
    launcher = main_module.BotLauncher()

    launcher.bot = SimpleNamespace(bot=SimpleNamespace())
    monkeypatch.setattr(
        launcher,
        "_stop_bot_operations",
        lambda: (_ for _ in ()).throw(RuntimeError("cleanup failed")),
    )
    launcher._cleanup_bot()
    assert launcher.bot is None

    launcher2 = main_module.BotLauncher()
    launcher2.bot = None
    launcher2._health_manager = None
    launcher2.shutdown()

    launcher3 = main_module.BotLauncher()
    launcher3.bot = SimpleNamespace(bot=SimpleNamespace())
    launcher3._health_manager = SimpleNamespace(stop=lambda timeout: None)
    monkeypatch.setattr(
        launcher3,
        "_stop_bot_operations",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(ShutdownError):
        launcher3.shutdown()

    monkeypatch.setattr(
        main_module.signal,
        "signal",
        lambda sig, handler: (
            (_ for _ in ()).throw(OSError("blocked")) if sig == signal.SIGTERM else None
        ),
    )
    launcher3._register_signal_handler(signal.SIGTERM)


def test_run_main_loop_keyboard_interrupt_breaks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_module = _load_main_module(monkeypatch)
    launcher = main_module.BotLauncher()

    _install_run_main_loop_stubs(
        monkeypatch=monkeypatch,
        main_module=main_module,
        launcher=launcher,
        polling_alive=True,
        should_log_health=lambda: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    launcher.run_main_loop()


def test_keyboard_interrupt_fatal_error_and_main_entrypoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    main_module = _load_main_module(monkeypatch)
    launcher = main_module.BotLauncher()

    monkeypatch.setattr(
        main_module.sys, "exit", lambda code: (_ for _ in ()).throw(SystemExit(code))
    )
    monkeypatch.setattr(
        launcher,
        "shutdown",
        lambda: (_ for _ in ()).throw(ShutdownError("stop failed")),
    )
    launcher._handle_keyboard_interrupt()

    monkeypatch.setattr(
        launcher,
        "shutdown",
        lambda: (_ for _ in ()).throw(RuntimeError("fatal stop failed")),
    )
    with pytest.raises(SystemExit) as fatal_exit:
        launcher._handle_fatal_error(RuntimeError("fatal"))
    assert fatal_exit.value.code == 1

    launcher2 = main_module.BotLauncher()
    monkeypatch.setattr(launcher2, "_register_cleanup", lambda: None)
    monkeypatch.setattr(launcher2, "_setup_signal_handlers", lambda: None)
    monkeypatch.setattr(launcher2, "validate_environment", lambda: None)
    monkeypatch.setattr(
        launcher2,
        "run_main_loop",
        lambda: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    monkeypatch.setattr(
        launcher2,
        "_handle_keyboard_interrupt",
        lambda: (_ for _ in ()).throw(SystemExit(0)),
    )
    with pytest.raises(SystemExit) as run_interrupt:
        launcher2.run()
    assert run_interrupt.value.code == 0

    called = {"health": 0, "run": 0}
    monkeypatch.setattr(
        main_module,
        "check_health",
        lambda: called.__setitem__("health", called["health"] + 1),
    )
    monkeypatch.setattr(
        main_module,
        "BotLauncher",
        lambda: SimpleNamespace(
            run=lambda: called.__setitem__("run", called["run"] + 1)
        ),
    )

    monkeypatch.setattr(
        main_module, "args", SimpleNamespace(health_check=True), raising=False
    )
    main_module.main()
    monkeypatch.setattr(
        main_module, "args", SimpleNamespace(health_check=False), raising=False
    )
    main_module.main()
    assert called == {"health": 1, "run": 1}
