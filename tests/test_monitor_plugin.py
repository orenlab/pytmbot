from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import cast

import pytest
from telebot import TeleBot
from telebot.types import Message

import pytmbot.plugins.monitor.plugin as monitor_plugin_module
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


def test_handle_cpu_usage_success(monkeypatch: pytest.MonkeyPatch) -> None:
    sent_messages: list[_PayloadDict] = []
    adapter_closed = {"value": False}

    class _Adapter:
        def get_cpu_usage(self) -> _PayloadDict:
            return {"cpu_percent": 12.3, "cpu_percent_per_core": [10.0, 14.6]}

        @staticmethod
        def get_load_average() -> tuple[float, float, float]:
            return (0.12, 0.34, 0.56)

        @staticmethod
        def get_top_processes(count: int = 5) -> list[_PayloadDict]:
            assert count == 5
            return [
                {
                    "pid": 123,
                    "name": "python",
                    "cpu_percent": 5.0,
                    "memory_percent": 1.1,
                }
            ]

        @staticmethod
        def close() -> None:
            adapter_closed["value"] = True

    monkeypatch.setattr(monitor_plugin_module, "PsutilAdapter", _Adapter)
    monkeypatch.setattr(
        monitor_plugin_module,
        "keyboards",
        type(
            "_Kbd",
            (),
            {
                "build_reply_keyboard": staticmethod(
                    lambda plugin_keyboard_data=None: "monitor-kbd"
                )
            },
        )(),
    )
    monkeypatch.setattr(
        monitor_plugin_module,
        "em",
        type("_Em", (), {"get_emoji": staticmethod(lambda _name: "📈")})(),
    )

    def _fake_send_message(
        self: TeleBot, chat_id: int, text: str, **kwargs: _PayloadValue
    ) -> Message:
        sent_messages.append({"chat_id": chat_id, "text": text, **kwargs})
        return cast(Message, cast(object, SimpleNamespace(ok=True)))

    monkeypatch.setattr(TeleBot, "send_message", _fake_send_message)

    plugin = MonitoringPlugin(TeleBot("12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE"))
    result = plugin.handle_cpu_usage(cast(Message, cast(object, _Message())))

    assert result is not None
    assert adapter_closed["value"] is False
    assert len(sent_messages) == 1
    assert sent_messages[0]["chat_id"] == 101
    assert "CPU usage snapshot" in str(sent_messages[0]["text"])
    assert "Overall: 12.3%" in str(sent_messages[0]["text"])
    assert sent_messages[0]["reply_markup"] == "monitor-kbd"
    plugin.cleanup()
    assert adapter_closed["value"] is True


def test_handle_cpu_usage_failure_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent_messages: list[_PayloadDict] = []
    adapter_closed = {"value": False}

    class _Adapter:
        @staticmethod
        def get_cpu_usage() -> _PayloadDict:
            raise RuntimeError("cpu snapshot failed")

        @staticmethod
        def close() -> None:
            adapter_closed["value"] = True

    monkeypatch.setattr(monitor_plugin_module, "PsutilAdapter", _Adapter)

    def _fake_send_message(
        self: TeleBot, chat_id: int, text: str, **kwargs: _PayloadValue
    ) -> Message:
        sent_messages.append({"chat_id": chat_id, "text": text, **kwargs})
        return cast(Message, cast(object, SimpleNamespace(ok=True)))

    monkeypatch.setattr(TeleBot, "send_message", _fake_send_message)

    plugin = MonitoringPlugin(TeleBot("12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE"))
    plugin.handle_cpu_usage(cast(Message, cast(object, _Message())))

    assert adapter_closed["value"] is False
    assert len(sent_messages) == 1
    assert "Failed to collect CPU usage metrics" in str(sent_messages[0]["text"])
    plugin.cleanup()
    assert adapter_closed["value"] is True
