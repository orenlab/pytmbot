from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, cast

import pytest
from telebot import TeleBot
from telebot.types import Message

import pytmbot.plugins.outline.plugin as outline_plugin_module
from pytmbot.plugins.outline.plugin import OutlinePlugin


@dataclass
class _User:
    first_name: str = "Den"


@dataclass
class _Chat:
    id: int = 101


@dataclass
class _Message:
    chat: _Chat = field(default_factory=_Chat)
    from_user: _User = field(default_factory=_User)


def _build_plugin_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[OutlinePlugin, list[dict[str, Any]], dict[str, Any]]:
    sent_messages: list[dict[str, Any]] = []
    rendered_context: dict[str, Any] = {}

    monkeypatch.setattr(
        outline_plugin_module,
        "em",
        cast(
            object, type("_Em", (), {"get_emoji": staticmethod(lambda _name: "🧪")})()
        ),
    )
    monkeypatch.setattr(TeleBot, "send_chat_action", lambda *_args, **_kwargs: None)

    def _fake_send_message(
        self: TeleBot, chat_id: int, text: str, **kwargs: object
    ) -> Message:
        sent_messages.append({"chat_id": chat_id, "text": text, **kwargs})
        return cast(Message, SimpleNamespace(ok=True))

    monkeypatch.setattr(TeleBot, "send_message", _fake_send_message)

    plugin = OutlinePlugin(TeleBot("12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE"))

    def _fake_compile(
        template_name: str,
        first_name: str,
        context: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> str:
        rendered_context["template_name"] = template_name
        rendered_context["first_name"] = first_name
        rendered_context["context"] = context
        return f"rendered-{template_name}"

    monkeypatch.setattr(plugin, "_compile_template", _fake_compile)
    return plugin, sent_messages, rendered_context


def test_handle_server_info_normalizes_snake_case_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin, sent_messages, rendered_context = _build_plugin_harness(monkeypatch)
    monkeypatch.setattr(
        plugin,
        "_get_action_data",
        lambda action: (
            {
                "name": "srv",
                "metrics_enabled": True,
                "created_timestamp_ms": 1234567890,
                "port_for_new_access_keys": 8443,
            }
            if action == "server_information"
            else None
        ),
    )

    plugin.handle_server_info(cast(Message, _Message()))

    assert rendered_context["template_name"] == "plugin_outline_server_info.jinja2"
    assert rendered_context["first_name"] == "Den"
    assert rendered_context["context"] == {
        "name": "srv",
        "metricsEnabled": True,
        "createdTimestampMs": 1234567890,
        "portForNewAccessKeys": 8443,
    }
    assert sent_messages[0]["chat_id"] == 101
    assert sent_messages[0]["text"] == "rendered-plugin_outline_server_info.jinja2"
    assert sent_messages[0]["parse_mode"] == "HTML"


def test_handle_traffic_supports_snake_case_and_key_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin, sent_messages, rendered_context = _build_plugin_harness(monkeypatch)

    def _fake_get_action_data(action: str) -> dict[str, Any] | None:
        if action == "traffic_information":
            return {"bytes_transferred_by_user_id": {"42": 4096}}
        if action == "key_information":
            return {"accessKeys": [{"key_id": "42", "name": "Alice"}]}
        return None

    monkeypatch.setattr(plugin, "_get_action_data", _fake_get_action_data)

    plugin.handle_traffic(cast(Message, _Message()))

    assert rendered_context["template_name"] == "plugin_outline_traffic.jinja2"
    assert rendered_context["first_name"] == "Den"
    assert rendered_context["context"] == {
        "bytesTransferredByUserId": {"42": 4096},
        "userNames": {"42": "Alice"},
    }
    assert sent_messages[0]["chat_id"] == 101
    assert sent_messages[0]["text"] == "rendered-plugin_outline_traffic.jinja2"
    assert sent_messages[0]["parse_mode"] == "HTML"


def test_get_action_data_parses_json_list_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = OutlinePlugin(TeleBot("12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE"))
    monkeypatch.setattr(
        plugin,
        "_get_plugin_methods",
        lambda: SimpleNamespace(
            outline_action_manager=lambda *, action: '[{"id": "1", "name": "Alice"}]'
        ),
    )

    result = plugin._get_action_data("key_information")
    assert result == {"accessKeys": [{"id": "1", "name": "Alice"}]}
