from __future__ import annotations

import argparse
import concurrent.futures
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import SimpleNamespace, TracebackType
from typing import cast

import pytest
import requests
import telebot
from telebot import TeleBot
from telebot.apihelper import ApiTelegramException
from telebot.types import BotCommand

import pytmbot.pytmbot_instance as instance_module
from pytmbot.exceptions import InitializationError
from pytmbot.plugins.plugin_manager import PluginManager

type _PayloadValue = (
    str | int | float | bool | None | dict[str, _PayloadValue] | list[_PayloadValue]
)
type _MessageCallback = Callable[..., None]
type _PredicateCallback = Callable[..., bool]


def _build_api_exception(error_code: int) -> ApiTelegramException:
    api_exc_ctor = cast(Callable[..., ApiTelegramException], ApiTelegramException)
    return api_exc_ctor(
        "getUpdates",
        SimpleNamespace(status_code=error_code, text="error"),
        {"error_code": error_code, "description": "error"},
    )


class _RateLimitApiException(ApiTelegramException):
    def __init__(self, retry_after: int) -> None:
        base_exc = _build_api_exception(429)
        Exception.__init__(self, *getattr(base_exc, "args", ("rate limit",)))
        self.__dict__.update(getattr(base_exc, "__dict__", {}))
        self.retry_after = retry_after


class _SecretValue:
    def __init__(self, value: str) -> None:
        self._value = value

    def get_secret_value(self) -> str:
        return self._value


@dataclass
class _DummyTeleBot:
    token: str = "12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE"
    polling: bool = False
    stop_calls: int = 0
    remove_calls: int = 0
    middleware_instances: list[SimpleNamespace] = field(default_factory=list)
    message_handlers: list[tuple[_MessageCallback, dict[str, _PayloadValue]]] = field(
        default_factory=list
    )
    callback_handlers: list[
        tuple[_MessageCallback, dict[str, _PayloadValue | _PredicateCallback]]
    ] = field(default_factory=list)
    commands_set: list[BotCommand] = field(default_factory=list)
    description_set: str = ""
    get_me_error: Exception | None = None

    def stop_polling(self) -> None:
        self.stop_calls += 1
        self.polling = False

    def remove_webhook(self) -> bool:
        self.remove_calls += 1
        return True

    def get_me(self) -> dict[str, str]:
        if self.get_me_error is not None:
            raise self.get_me_error
        return {"ok": "true"}

    def set_my_commands(
        self,
        commands: list[BotCommand],
        scope: SimpleNamespace | None = None,
        language_code: str | None = None,
    ) -> bool:
        del scope, language_code
        self.commands_set = commands
        return True

    def set_my_description(
        self,
        description: str | None = None,
        language_code: str | None = None,
    ) -> None:
        del language_code
        self.description_set = description or ""

    def setup_middleware(self, middleware: SimpleNamespace) -> None:
        self.middleware_instances.append(middleware)

    def register_message_handler(
        self,
        callback: _MessageCallback,
        **kwargs: _PayloadValue,
    ) -> None:
        self.message_handlers.append((callback, kwargs))

    def register_callback_query_handler(
        self,
        callback: _MessageCallback,
        func: _PredicateCallback,
        pass_bot: bool | None = False,
        **kwargs: _PayloadValue,
    ) -> None:
        self.callback_handlers.append(
            (
                callback,
                {"func": func, "pass_bot": pass_bot, **kwargs},
            )
        )

    def infinity_polling(self, **_kwargs: _PayloadValue) -> None:
        return


def _set_bot_args(
    bot: instance_module.PyTMBot,
    *,
    plugins: list[str],
    webhook: str = "False",
    socket_host: str = "127.0.0.1",
) -> None:
    bot.args = argparse.Namespace(
        mode="dev",
        webhook=webhook,
        plugins=plugins,
        socket_host=socket_host,
    )


def _build_bot_with_dummy_telebot(
    monkeypatch: pytest.MonkeyPatch,
) -> instance_module.PyTMBot:
    bot = instance_module.PyTMBot()
    monkeypatch.setattr(instance_module, "TeleBot", _DummyTeleBot)
    bot.bot = cast(TeleBot, _DummyTeleBot())
    return bot


def test_bot_session_create_populates_fields() -> None:
    session = instance_module.BotSession.create(mode="dev", webhook_enabled=False)
    assert len(session.session_id) == 8
    assert session.mode == "dev"
    assert session.webhook_enabled is False


def test_is_critical_api_error_maps_known_and_unknown_codes() -> None:
    is_critical, kind = instance_module.PyTMBot._is_critical_api_error(
        _build_api_exception(401)
    )
    assert is_critical is True
    assert kind == "unauthorized"

    is_unknown_critical, unknown_kind = instance_module.PyTMBot._is_critical_api_error(
        _build_api_exception(499)
    )
    assert is_unknown_critical is False
    assert unknown_kind == "unknown"


def test_handle_critical_api_error_rate_limit_recovers_and_caps_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = instance_module.PyTMBot()
    sleeps: list[int] = []
    error = _RateLimitApiException(900)

    monkeypatch.setattr(
        "pytmbot.pytmbot_instance.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    assert bot._handle_critical_api_error(error, "rate_limited") is True
    assert sleeps == [300]


def test_handle_critical_api_error_opens_rate_limit_circuit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = instance_module.PyTMBot()
    sleeps: list[int] = []
    monkeypatch.setattr(
        "pytmbot.pytmbot_instance.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    for _ in range(instance_module.RATE_LIMIT_CIRCUIT_THRESHOLD):
        assert (
            bot._handle_critical_api_error(_RateLimitApiException(120), "rate_limited")
            is True
        )

    assert sleeps == [120, 120, 300]
    assert bot._rate_limit_open_until is not None
    assert bot._rate_limit_consecutive == instance_module.RATE_LIMIT_CIRCUIT_THRESHOLD


def test_handle_critical_api_error_respects_open_rate_limit_circuit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = instance_module.PyTMBot()
    bot._rate_limit_consecutive = instance_module.RATE_LIMIT_CIRCUIT_THRESHOLD
    bot._rate_limit_open_until = datetime.now() + timedelta(seconds=42)
    sleeps: list[int] = []
    monkeypatch.setattr(
        "pytmbot.pytmbot_instance.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    assert (
        bot._handle_critical_api_error(_RateLimitApiException(5), "rate_limited")
        is True
    )
    assert len(sleeps) == 1
    assert 1 <= sleeps[0] <= 42


def test_safe_stop_polling_returns_true_when_bot_missing() -> None:
    bot = instance_module.PyTMBot()
    bot.bot = None
    assert bot._safe_stop_polling() is True


def test_safe_stop_polling_handles_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    class _TimeoutFuture:
        def result(self, timeout: int) -> bool:
            raise concurrent.futures.TimeoutError(timeout)

    class _TimeoutExecutor:
        def __enter__(self) -> _TimeoutExecutor:
            return self

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: TracebackType | None,
        ) -> None:
            return

        def submit(self, _func: Callable[[], None]) -> _TimeoutFuture:
            return _TimeoutFuture()

    bot = instance_module.PyTMBot()
    dummy = _DummyTeleBot()
    bot.bot = cast(TeleBot, dummy)
    monkeypatch.setattr(concurrent.futures, "ThreadPoolExecutor", _TimeoutExecutor)

    assert bot._safe_stop_polling(timeout=1) is False
    assert bot._shutdown_timeout_occurred is True


def test_handle_polling_error_connection_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = instance_module.PyTMBot()
    sleeps: list[int] = []
    monkeypatch.setattr(
        "pytmbot.pytmbot_instance.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    errors, sleep_time = bot._handle_polling_error(
        requests.exceptions.ConnectionError("temporary"),
        consecutive_errors=0,
        current_sleep_time=10,
    )

    assert errors == 1
    assert sleep_time == 20
    assert sleeps == [10]


def test_handle_polling_error_raises_original_unrecoverable_api_error() -> None:
    bot = instance_module.PyTMBot()
    error = _build_api_exception(401)

    with pytest.raises(ApiTelegramException):
        bot._handle_polling_error(error, consecutive_errors=0, current_sleep_time=10)


def test_retrieve_bot_token_supports_dev_and_prod(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = instance_module.PyTMBot()
    settings_stub = SimpleNamespace(
        bot_token=SimpleNamespace(
            dev_bot_token=[_SecretValue("dev-token")],
            prod_token=[_SecretValue("prod-token")],
        )
    )
    monkeypatch.setattr(instance_module, "settings", settings_stub)

    bot.args = argparse.Namespace(mode="dev", webhook="False", plugins=[])
    assert bot.retrieve_bot_token() == "dev-token"

    bot.args = argparse.Namespace(mode="prod", webhook="False", plugins=[])
    assert bot.retrieve_bot_token() == "prod-token"


def test_setup_middleware_chain_and_stats(monkeypatch: pytest.MonkeyPatch) -> None:
    class RateLimitLike:
        def __init__(self, bot: TeleBot, *, limit: int) -> None:
            self.bot = bot
            self.limit = limit
            self.cleaned = False

        def get_stats(self) -> dict[str, int]:
            return {"limit": self.limit}

        def cleanup(self) -> None:
            self.cleaned = True

    bot = instance_module.PyTMBot()
    dummy = _DummyTeleBot()
    bot.bot = cast(TeleBot, dummy)
    monkeypatch.setattr(instance_module, "TeleBot", _DummyTeleBot)

    bot._setup_middleware_chain([(RateLimitLike, {"limit": 5})])
    assert bot.get_middleware_stats("RateLimitLike") == {"limit": 5}
    assert bot.get_middleware_stats("MissingMiddleware") is None


def test_default_middlewares_start_with_update_dedup() -> None:
    middleware_names = [
        middleware[0].__name__ for middleware in instance_module.DEFAULT_MIDDLEWARES
    ]
    assert middleware_names[0] == "UpdateDedup"


def test_register_handler_chain_registers_message_and_callback_handlers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = instance_module.PyTMBot()
    dummy = _DummyTeleBot()
    bot.bot = cast(TeleBot, dummy)
    monkeypatch.setattr(instance_module, "TeleBot", _DummyTeleBot)

    message_handler = SimpleNamespace(
        callback=lambda _message, _bot: None,
        kwargs={"commands": ["start"]},
    )
    callback_handler = SimpleNamespace(
        callback=lambda _query, _bot: None,
        kwargs={"func": lambda _query: True},
    )

    monkeypatch.setattr(
        instance_module,
        "handler_factory",
        lambda: {"messages": [message_handler]},
    )
    monkeypatch.setattr(
        instance_module,
        "inline_handler_factory",
        lambda: {"callbacks": [callback_handler]},
    )

    bot._register_handler_chain()

    assert len(dummy.message_handlers) == 1
    assert len(dummy.callback_handlers) == 1


def test_initialize_bot_core_sets_running_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = instance_module.PyTMBot()
    dummy = _DummyTeleBot()

    monkeypatch.setattr(
        instance_module.PyTMBot,
        "retrieve_bot_token",
        lambda self: "token",
    )
    monkeypatch.setattr(
        instance_module.PyTMBot,
        "_create_base_bot",
        lambda self, _token: cast(TeleBot, dummy),
    )
    monkeypatch.setattr(
        instance_module.PyTMBot,
        "_configure_bot_features",
        lambda self: None,
    )

    initialized = bot.initialize_bot_core()

    assert initialized is cast(TeleBot, dummy)
    assert bot.state is instance_module.BotState.RUNNING


def test_get_bot_session_statistics_includes_runtime_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = instance_module.PyTMBot()
    dummy = _DummyTeleBot(polling=True)
    bot.bot = cast(TeleBot, dummy)

    monkeypatch.setattr(instance_module.PyTMBot, "is_healthy", lambda self: True)
    monkeypatch.setattr(
        instance_module.PyTMBot,
        "get_rate_limit_stats",
        lambda self: {"active_users": 1},
    )

    stats = bot.get_bot_session_statistics()

    assert stats["bot_healthy"] is True
    assert stats["polling_active"] is True
    assert stats["rate_limit_stats"] == {"active_users": 1}


def test_handle_bot_conflict_strategy_dispatch(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = instance_module.PyTMBot()
    called: list[str] = []

    def _graceful(self: instance_module.PyTMBot) -> bool:
        called.append("graceful")
        return True

    def _force(self: instance_module.PyTMBot) -> bool:
        called.append("force")
        return True

    def _abort(self: instance_module.PyTMBot) -> bool:
        called.append("abort")
        return False

    monkeypatch.setattr(
        instance_module.PyTMBot,
        "_graceful_conflict_resolution",
        _graceful,
    )
    monkeypatch.setattr(
        instance_module.PyTMBot,
        "_force_takeover",
        _force,
    )
    monkeypatch.setattr(
        instance_module.PyTMBot,
        "_abort_on_conflict",
        _abort,
    )

    assert (
        bot._handle_bot_conflict(
            instance_module.ConflictResolutionStrategy.GRACEFUL_SHUTDOWN
        )
        is True
    )
    assert (
        bot._handle_bot_conflict(
            instance_module.ConflictResolutionStrategy.FORCE_TAKEOVER
        )
        is True
    )
    assert (
        bot._handle_bot_conflict(instance_module.ConflictResolutionStrategy.ABORT)
        is False
    )
    assert called == ["graceful", "force", "abort"]


def test_graceful_conflict_and_force_takeover_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = instance_module.PyTMBot()
    bot.bot = cast(TeleBot, _DummyTeleBot())

    monkeypatch.setattr(
        instance_module.PyTMBot,
        "_safe_stop_polling",
        lambda self: (_ for _ in ()).throw(RuntimeError("stop failed")),
    )
    assert bot._graceful_conflict_resolution() is False

    class _FailingRemove:
        def remove_webhook(self) -> bool:
            raise RuntimeError("remove failed")

    bot.bot = cast(TeleBot, _FailingRemove())
    assert bot._force_takeover() is False


def test_polling_safety_context_conflict_and_reraise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = instance_module.PyTMBot()
    bot.bot = cast(TeleBot, _DummyTeleBot())
    stop_calls: list[str] = []

    def _stop(self: instance_module.PyTMBot) -> bool:
        stop_calls.append("stop")
        return True

    monkeypatch.setattr(
        instance_module.PyTMBot,
        "_safe_stop_polling",
        _stop,
    )
    monkeypatch.setattr(
        instance_module.PyTMBot,
        "_is_bot_conflict_error",
        lambda self, error: True,
    )
    monkeypatch.setattr(
        instance_module.PyTMBot, "_handle_bot_conflict", lambda self: True
    )

    with bot._polling_safety_context():
        raise RuntimeError("409 conflict")

    assert stop_calls == ["stop"]

    stop_calls.clear()
    monkeypatch.setattr(
        instance_module.PyTMBot,
        "_is_bot_conflict_error",
        lambda self, error: False,
    )
    with pytest.raises(ValueError):
        with bot._polling_safety_context():
            raise ValueError("hard failure")
    assert stop_calls == ["stop"]


def test_is_healthy_state_checks() -> None:
    bot = instance_module.PyTMBot()
    assert bot.is_healthy() is False

    dummy = _DummyTeleBot(polling=False)
    bot.bot = cast(TeleBot, dummy)
    bot._state = instance_module.BotState.RUNNING
    bot._session = instance_module.BotSession.create(mode="dev", webhook_enabled=False)
    assert bot.is_healthy() is False

    dummy.polling = True
    assert bot.is_healthy() is True

    bot._state = instance_module.BotState.ERROR
    assert bot.is_healthy() is False


def test_retrieve_bot_token_error_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = instance_module.PyTMBot()
    bot.args = argparse.Namespace(mode="dev", webhook="False", plugins=[])

    missing_dev_settings = SimpleNamespace(
        bot_token=SimpleNamespace(
            dev_bot_token=[],
            prod_token=[_SecretValue("prod-token")],
        )
    )
    monkeypatch.setattr(instance_module, "settings", missing_dev_settings)
    with pytest.raises(InitializationError) as dev_exc:
        bot.retrieve_bot_token()
    assert dev_exc.value.context.error_code == "CORE_001_DEV"

    monkeypatch.setattr(instance_module, "settings", SimpleNamespace())
    with pytest.raises(InitializationError) as attr_exc:
        bot.retrieve_bot_token()
    assert attr_exc.value.context.error_code == "CORE_001"


def test_start_webhook_server_requires_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = instance_module.PyTMBot()
    dummy = _DummyTeleBot()
    bot.bot = cast(TeleBot, dummy)
    bot.args = argparse.Namespace(
        mode="dev",
        webhook="True",
        plugins=[],
        socket_host="127.0.0.1",
    )

    monkeypatch.setattr(instance_module, "TeleBot", _DummyTeleBot)
    monkeypatch.setattr(
        instance_module, "settings", SimpleNamespace(webhook_config=None)
    )

    with pytest.raises(InitializationError) as exc_info:
        bot._start_webhook_server()
    assert exc_info.value.context.error_code == "CORE_WEBHOOK_001"


def test_bot_required_and_critical_api_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = instance_module.PyTMBot()
    with pytest.raises(RuntimeError):
        bot._setup_commands_and_description()

    monkeypatch.setattr(
        instance_module.PyTMBot,
        "_handle_bot_conflict",
        lambda self: True,
    )
    assert (
        bot._handle_critical_api_error(_build_api_exception(401), "unauthorized")
        is False
    )
    assert bot._handle_critical_api_error(_build_api_exception(409), "conflict") is True
    assert (
        bot._handle_critical_api_error(_build_api_exception(502), "bad_gateway") is True
    )
    assert bot._handle_critical_api_error(_build_api_exception(499), "unknown") is False


def test_conflict_resolution_success_and_polling_context_unresolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = instance_module.PyTMBot()
    dummy = _DummyTeleBot(polling=True)
    bot.bot = cast(TeleBot, dummy)
    sleeps: list[int] = []
    monkeypatch.setattr(
        instance_module, "sleep", lambda seconds: sleeps.append(seconds)
    )

    assert bot._graceful_conflict_resolution() is True
    assert bot._force_takeover() is True
    assert sleeps == [20, 5]

    monkeypatch.setattr(
        instance_module.PyTMBot, "_is_bot_conflict_error", lambda self, error: True
    )
    monkeypatch.setattr(
        instance_module.PyTMBot, "_handle_bot_conflict", lambda self: False
    )
    with pytest.raises(RuntimeError):
        with bot._polling_safety_context():
            raise RuntimeError("conflict unresolved")


def test_safe_stop_polling_failure_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    class _FailingStopBot:
        polling: bool = True

        def stop_polling(self) -> None:
            raise RuntimeError("stop failed")

    bot = instance_module.PyTMBot()
    bot.bot = cast(TeleBot, _FailingStopBot())
    assert bot._safe_stop_polling(timeout=1) is False

    class _BrokenExecutor:
        def __enter__(self) -> _BrokenExecutor:
            raise RuntimeError("executor failed")

        def __exit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _tb: TracebackType | None,
        ) -> None:
            return

    monkeypatch.setattr(concurrent.futures, "ThreadPoolExecutor", _BrokenExecutor)
    assert bot._safe_stop_polling(timeout=1) is False


def test_create_base_bot_and_commands_exception_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = instance_module.PyTMBot()
    monkeypatch.setattr(
        telebot,
        "TeleBot",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("create failed")),
    )
    with pytest.raises(RuntimeError):
        bot._create_base_bot("token")

    class _ApiErrorBot(_DummyTeleBot):
        def set_my_commands(
            self,
            commands: list[BotCommand],
            scope: SimpleNamespace | None = None,
            language_code: str | None = None,
        ) -> bool:
            del commands, scope, language_code
            raise _build_api_exception(400)

    monkeypatch.setattr(instance_module, "TeleBot", _ApiErrorBot)
    bot.bot = cast(TeleBot, _ApiErrorBot())
    bot._setup_commands_and_description()


def test_middleware_register_and_plugin_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    class _StatsNotDict:
        def get_stats(self) -> str:
            return "not-dict"

    class _StatsFail:
        def get_stats(self) -> dict[str, int]:
            raise RuntimeError("stats failed")

    class _BrokenMiddleware:
        def __init__(self, bot: TeleBot, **kwargs: _PayloadValue) -> None:
            del bot, kwargs
            raise RuntimeError("middleware failed")

    bot = _build_bot_with_dummy_telebot(monkeypatch)

    with pytest.raises(RuntimeError):
        bot._setup_middleware_chain([(_BrokenMiddleware, {})])

    bot._middlewares = {"a": _StatsNotDict(), "b": _StatsFail()}
    assert bot.get_middleware_stats("a") is None
    assert bot.get_middleware_stats("b") is None

    _set_bot_args(bot, plugins=[], webhook="False")
    bot._load_plugins()
    _set_bot_args(bot, plugins=["", "  "], webhook="False")
    bot._load_plugins()

    _set_bot_args(bot, plugins=["one"], webhook="False")
    bot.plugin_manager = cast(
        PluginManager,
        SimpleNamespace(
            register_plugins=lambda plugins, telebot: (_ for _ in ()).throw(
                RuntimeError("plugin failed")
            )
        ),
    )
    with pytest.raises(RuntimeError):
        bot._load_plugins()


def test_start_webhook_server_success_and_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _build_bot_with_dummy_telebot(monkeypatch)
    _set_bot_args(bot, plugins=[], webhook="True")
    monkeypatch.setattr(
        instance_module,
        "settings",
        SimpleNamespace(webhook_config=SimpleNamespace(local_port=[8443])),
    )

    starts: list[tuple[str, str, str]] = []

    class _WebhookServer:
        def __init__(self, bot_obj: TeleBot, **config: _PayloadValue) -> None:
            del bot_obj
            starts.append(
                (
                    str(config["host"]),
                    str(config["port"]),
                    str(config["token"]),
                )
            )

        def start(self) -> None:
            return

    fake_webhook_module = SimpleNamespace(WebhookServer=_WebhookServer)
    monkeypatch.setitem(sys.modules, "pytmbot.webhook", fake_webhook_module)
    bot._start_webhook_server()
    assert starts and starts[0][1] == "8443"

    class _FailingWebhookServer:
        def __init__(self, bot_obj: TeleBot, **config: _PayloadValue) -> None:
            del bot_obj, config

        def start(self) -> None:
            raise RuntimeError("webhook start failed")

    monkeypatch.setitem(
        sys.modules,
        "pytmbot.webhook",
        SimpleNamespace(WebhookServer=_FailingWebhookServer),
    )
    with pytest.raises(RuntimeError):
        bot._start_webhook_server()


def test_get_session_stats_without_session() -> None:
    bot = instance_module.PyTMBot()
    bot._session = None
    assert bot.get_bot_session_statistics() == {}
