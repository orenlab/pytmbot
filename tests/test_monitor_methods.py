from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, cast

import pytest
from telebot import TeleBot

import pytmbot.plugins.monitor.methods as monitor_methods_module
from pytmbot.plugins.monitor.methods import SystemMonitorPlugin
from pytmbot.plugins.monitor.models import MonitoringState


@dataclass
class _BotStub:
    sent_messages: list[dict[str, object]] = field(default_factory=list)

    def send_message(
        self, chat_id: int, text: str, parse_mode: str | None = None
    ) -> None:
        self.sent_messages.append(
            {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        )


def _build_monitor(
    *,
    max_notifications: int = 2,
    reset_window_seconds: int = 300,
) -> tuple[SystemMonitorPlugin, _BotStub]:
    monitor = cast(SystemMonitorPlugin, object.__new__(SystemMonitorPlugin))
    bot = _BotStub()
    monitor.bot = cast(TeleBot, bot)
    monitor.monitor_settings = cast(
        Any,
        SimpleNamespace(
            max_notifications=[max_notifications],
            reset_notification_count=[reset_window_seconds],
            retry_interval=[1],
        ),
    )
    monitor.state = MonitoringState()
    monitor.settings = cast(
        Any, SimpleNamespace(chat_id=SimpleNamespace(global_chat_id=[999]))
    )
    monitor._monitor_thread = None
    monitor._supervisor_thread = None
    monitor._monitor_thread_lock = monitor_methods_module.threading.RLock()
    monitor._monitor_restart_count = 0
    return monitor, bot


def test_send_notification_does_not_spawn_timer_threads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor, bot = _build_monitor(max_notifications=2, reset_window_seconds=300)
    monkeypatch.setattr(monitor_methods_module.time, "time", lambda: 100.0)
    monkeypatch.setattr(
        monitor_methods_module.threading,
        "Timer",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("Timer must not be used")
        ),
    )

    monitor._send_notification("alert-1")
    monitor._send_notification("alert-2")
    monitor._send_notification("alert-3")

    assert len(bot.sent_messages) == 2
    assert monitor.state.notification_count == 2
    assert monitor.state.max_notifications_reached is True
    assert monitor.state.next_notification_reset_at == 400.0


def test_send_notification_resets_budget_lazily_after_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor, bot = _build_monitor(max_notifications=2, reset_window_seconds=300)
    timestamps = iter([100.0, 101.0, 500.0])
    monkeypatch.setattr(monitor_methods_module.time, "time", lambda: next(timestamps))

    monitor._send_notification("alert-1")
    monitor._send_notification("alert-2")
    monitor._send_notification("alert-3")

    assert len(bot.sent_messages) == 3
    assert monitor.state.notification_count == 1
    assert monitor.state.max_notifications_reached is False
    assert monitor.state.next_notification_reset_at == 800.0


def test_supervisor_restarts_dead_monitor_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monitor, _bot = _build_monitor(max_notifications=2, reset_window_seconds=300)
    monitor.state.is_active = True

    class _DeadThread:
        @staticmethod
        def is_alive() -> bool:
            return False

    class _LiveThread:
        @staticmethod
        def is_alive() -> bool:
            return True

    monitor._monitor_thread = cast(Any, _DeadThread())

    def _spawn() -> _LiveThread:
        monitor.state.is_active = False
        return _LiveThread()

    monkeypatch.setattr(monitor, "_spawn_monitor_thread", _spawn)
    monkeypatch.setattr(monitor_methods_module.time, "sleep", lambda _seconds: None)

    monitor._supervise_monitoring()

    assert isinstance(monitor._monitor_thread, _LiveThread)
    assert monitor._monitor_restart_count == 1
