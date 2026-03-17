from __future__ import annotations

import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import ClassVar, cast

import pytest
from telebot import TeleBot
from telebot.types import Message

import pytmbot.plugins.monitor.plugin as monitor_plugin_module
from pytmbot.plugins.monitor import config as monitor_config
from pytmbot.plugins.monitor.plugin import MonitoringPlugin

type _PayloadScalar = str | int | float | bool | None
type _PayloadValue = _PayloadScalar | list["_PayloadValue"] | dict[str, "_PayloadValue"]
type _PayloadDict = dict[str, _PayloadValue]


@dataclass
class _Chat:
    id: int = 101


@dataclass
class _Message:
    chat: _Chat = field(default_factory=_Chat)
    text: str | None = None


class _StubMonitorAdapter:
    cpu_percent: ClassVar[float] = 0.0
    cpu_percent_per_core: ClassVar[list[float]] = []
    memory_percent: ClassVar[float] = 0.0
    disk_percent: ClassVar[float] = 0.0
    sensor_value: ClassVar[float] = 0.0
    load_average: ClassVar[tuple[float, float, float]] = (0.0, 0.0, 0.0)
    top_processes: ClassVar[list[_PayloadDict]] = []
    fail_cpu_usage: ClassVar[bool] = False
    last_top_count: ClassVar[int | None] = None
    closed_state: ClassVar[dict[str, bool] | None] = None

    @classmethod
    def configure(
        cls,
        *,
        cpu_percent: float = 0.0,
        cpu_percent_per_core: list[float] | None = None,
        memory_percent: float = 0.0,
        disk_percent: float = 0.0,
        sensor_value: float = 0.0,
        load_average: tuple[float, float, float] = (0.0, 0.0, 0.0),
        top_processes: list[_PayloadDict] | None = None,
        fail_cpu_usage: bool = False,
        closed_state: dict[str, bool] | None = None,
    ) -> None:
        cls.cpu_percent = cpu_percent
        cls.cpu_percent_per_core = list(cpu_percent_per_core or [])
        cls.memory_percent = memory_percent
        cls.disk_percent = disk_percent
        cls.sensor_value = sensor_value
        cls.load_average = load_average
        cls.top_processes = list(top_processes or [])
        cls.fail_cpu_usage = fail_cpu_usage
        cls.last_top_count = None
        cls.closed_state = closed_state

    @classmethod
    def get_cpu_usage(cls) -> _PayloadDict:
        if cls.fail_cpu_usage:
            raise RuntimeError("cpu snapshot failed")
        return {
            "cpu_percent": cls.cpu_percent,
            "cpu_percent_per_core": list(cls.cpu_percent_per_core),
        }

    @classmethod
    def get_load_average(cls) -> tuple[float, float, float]:
        return cls.load_average

    @classmethod
    def get_top_processes(cls, count: int = 5) -> list[_PayloadDict]:
        cls.last_top_count = count
        return list(cls.top_processes)

    @classmethod
    def get_memory(cls) -> _PayloadDict:
        return {"percent": cls.memory_percent}

    @classmethod
    def get_disk_usage(cls) -> list[_PayloadDict]:
        return [{"mnt_point": "/", "percent": cls.disk_percent}]

    @classmethod
    def get_sensors_temperatures(cls) -> list[_PayloadDict]:
        return [{"sensor_name": "cpu", "sensor_value": cls.sensor_value}]

    @classmethod
    def close(cls) -> None:
        if cls.closed_state is not None:
            cls.closed_state["value"] = True


def _patch_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(monitor_plugin_module, "PsutilAdapter", _StubMonitorAdapter)


def _patch_send_message(
    monkeypatch: pytest.MonkeyPatch, sent_messages: list[_PayloadDict]
) -> None:
    def _fake_send_message(
        self: TeleBot, chat_id: int, text: str, **kwargs: _PayloadValue
    ) -> Message:
        sent_messages.append({"chat_id": chat_id, "text": text, **kwargs})
        return cast(Message, cast(object, SimpleNamespace(ok=True)))

    monkeypatch.setattr(TeleBot, "send_message", _fake_send_message)


def _patch_ui_helpers(
    monkeypatch: pytest.MonkeyPatch, *, keyboard_name: str, emoji: str
) -> None:
    monkeypatch.setattr(
        monitor_plugin_module,
        "keyboards",
        type(
            "_Kbd",
            (),
            {
                "build_reply_keyboard": staticmethod(
                    lambda plugin_keyboard_data=None: keyboard_name
                )
            },
        )(),
    )
    monkeypatch.setattr(
        monitor_plugin_module,
        "em",
        type("_Em", (), {"get_emoji": staticmethod(lambda _name: emoji)})(),
    )


def test_handle_cpu_usage_success(monkeypatch: pytest.MonkeyPatch) -> None:
    sent_messages: list[_PayloadDict] = []
    adapter_closed = {"value": False}
    _StubMonitorAdapter.configure(
        cpu_percent=12.3,
        cpu_percent_per_core=[10.0, 14.6],
        load_average=(0.12, 0.34, 0.56),
        top_processes=[
            {
                "pid": 123,
                "name": "python",
                "cpu_percent": 5.0,
                "memory_percent": 1.1,
            }
        ],
        closed_state=adapter_closed,
    )
    _patch_adapter(monkeypatch)
    _patch_ui_helpers(monkeypatch, keyboard_name="monitor-kbd", emoji="📈")
    _patch_send_message(monkeypatch, sent_messages)

    plugin = MonitoringPlugin(TeleBot("12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE"))
    result = plugin.handle_cpu_usage(cast(Message, cast(object, _Message())))

    assert result is not None
    assert adapter_closed["value"] is False
    assert len(sent_messages) == 1
    assert sent_messages[0]["chat_id"] == 101
    assert "<b>CPU usage</b>" in str(sent_messages[0]["text"])
    assert "Latest CPU usage: 12.3%" in str(sent_messages[0]["text"])
    assert sent_messages[0]["reply_markup"] == "monitor-kbd"
    assert sent_messages[0]["parse_mode"] == "HTML"
    assert _StubMonitorAdapter.last_top_count == 5
    plugin.cleanup()
    assert adapter_closed["value"] is True


def test_handle_cpu_usage_failure_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent_messages: list[_PayloadDict] = []
    adapter_closed = {"value": False}
    _StubMonitorAdapter.configure(fail_cpu_usage=True, closed_state=adapter_closed)
    _patch_adapter(monkeypatch)
    _patch_send_message(monkeypatch, sent_messages)

    plugin = MonitoringPlugin(TeleBot("12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE"))
    plugin.handle_cpu_usage(cast(Message, cast(object, _Message())))

    assert adapter_closed["value"] is False
    assert len(sent_messages) == 1
    assert "Failed to collect CPU usage metrics" in str(sent_messages[0]["text"])
    plugin.cleanup()
    assert adapter_closed["value"] is True


def test_handle_monitoring_uses_html_parse_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent_messages: list[_PayloadDict] = []
    _StubMonitorAdapter.configure(
        cpu_percent=21.7,
        cpu_percent_per_core=[21.7],
        memory_percent=48.1,
        disk_percent=71.4,
        sensor_value=59.0,
    )
    _patch_adapter(monkeypatch)
    _patch_ui_helpers(monkeypatch, keyboard_name="monitor-main-kbd", emoji="ℹ️")
    _patch_send_message(monkeypatch, sent_messages)

    plugin = MonitoringPlugin(TeleBot("12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE"))
    plugin.handle_monitoring(cast(Message, cast(object, _Message())))

    assert len(sent_messages) == 1
    assert "<b>Monitoring dashboard</b>" in str(sent_messages[0]["text"])
    assert sent_messages[0]["parse_mode"] == "HTML"
    assert sent_messages[0]["reply_markup"] == "monitor-main-kbd"
    plugin.cleanup()


def test_handle_period_choice_updates_selected_period(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent_messages: list[_PayloadDict] = []
    _StubMonitorAdapter.configure(
        cpu_percent=10.0,
        cpu_percent_per_core=[10.0],
        memory_percent=11.0,
        disk_percent=22.0,
        sensor_value=33.0,
    )
    _patch_adapter(monkeypatch)
    _patch_ui_helpers(monkeypatch, keyboard_name="monitor-main-kbd", emoji="ℹ️")
    _patch_send_message(monkeypatch, sent_messages)

    plugin = MonitoringPlugin(TeleBot("12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE"))
    period_message = _Message()
    period_message.text = monitor_config.PERIOD_PRESETS["24h"]["label"]
    plugin.handle_period_choice(cast(Message, cast(object, period_message)))

    assert len(sent_messages) == 1
    assert "Period updated: Last 24 hours" in str(sent_messages[0]["text"])
    assert sent_messages[0]["parse_mode"] == "HTML"
    plugin.cleanup()


def test_handle_period_choice_accepts_emoji_prefixed_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent_messages: list[_PayloadDict] = []
    _StubMonitorAdapter.configure(
        cpu_percent=15.0,
        cpu_percent_per_core=[15.0],
        memory_percent=25.0,
        disk_percent=35.0,
        sensor_value=45.0,
    )
    _patch_adapter(monkeypatch)
    _patch_ui_helpers(monkeypatch, keyboard_name="monitor-main-kbd", emoji="ℹ️")
    _patch_send_message(monkeypatch, sent_messages)

    plugin = MonitoringPlugin(TeleBot("12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE"))
    period_message = _Message()
    period_message.text = "⏳ Last 15 minutes"
    plugin.handle_period_choice(cast(Message, cast(object, period_message)))

    assert len(sent_messages) == 1
    assert "Period updated: Last 15 minutes" in str(sent_messages[0]["text"])
    assert "Unknown period option" not in str(sent_messages[0]["text"])
    plugin.cleanup()


def test_button_regexp_matches_plain_and_emoji_prefixed_titles() -> None:
    regex = MonitoringPlugin._button_regexp("Monitoring")
    assert re.match(regex, "Monitoring")
    assert re.match(regex, "📈 Monitoring")
    assert not re.match(regex, "Server Monitoring")


def test_period_keyboard_uses_supported_hourglass_key() -> None:
    assert "hourglass_not_done" in monitor_config.PERIOD_KEYBOARD
    assert "hourglass_flowing_sand" not in monitor_config.PERIOD_KEYBOARD
