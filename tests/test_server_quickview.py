from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, cast

import pytest
from telebot import TeleBot
from telebot.types import Message

import pytmbot.handlers.server_handlers.quickview as quickview
from pytmbot.exceptions import HandlingException


def _build_bot(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[TeleBot, list[tuple[int, str]], list[dict[str, object]]]:
    bot = TeleBot("12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE")
    actions: list[tuple[int, str]] = []
    messages: list[dict[str, object]] = []

    def _send_chat_action(
        chat_id: int | str,
        action: str,
        timeout: int | None = None,
        message_thread_id: int | None = None,
        business_connection_id: str | None = None,
    ) -> bool:
        del timeout, message_thread_id, business_connection_id
        actions.append((int(chat_id), action))
        return True

    def _send_message(
        chat_id: int | str,
        text: str,
        parse_mode: str | None = None,
        **kwargs: object,
    ) -> dict[str, object]:
        del kwargs
        payload = {"chat_id": int(chat_id), "text": text, "parse_mode": parse_mode}
        messages.append(payload)
        return payload

    monkeypatch.setattr(bot, "send_chat_action", _send_chat_action)
    monkeypatch.setattr(bot, "send_message", _send_message)
    return bot, actions, messages


@dataclass
class _ExplodingAdapter:
    def get_uptime(self) -> str:
        raise RuntimeError("uptime error")

    def get_load_average(self) -> tuple[float, float, float]:
        raise RuntimeError("load error")

    def get_memory(self) -> dict[str, object]:
        raise RuntimeError("memory error")

    def get_process_counts(self) -> dict[str, object]:
        raise RuntimeError("proc error")


def _build_message(chat_id: int = 1) -> Message:
    payload = {
        "message_id": 1,
        "date": 1,
        "chat": {"id": chat_id, "type": "private"},
        "from": {"id": 101, "is_bot": False, "first_name": "Test"},
        "text": "quick view",
    }
    message_obj = Message.de_json(payload)
    if not isinstance(message_obj, Message):
        raise AssertionError("Expected Message instance")
    return message_obj


def test_quickview_metric_collectors_happy_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = SimpleNamespace(
        get_uptime=lambda: "1h 10m",
        get_load_average=lambda: (0.1, 0.2, 0.3),
        get_memory=lambda: {"percent": 42.0},
        get_process_counts=lambda: {"running": 1, "sleeping": 3},
    )
    monkeypatch.setattr(quickview, "psutil_adapter", adapter)
    monkeypatch.setattr(
        quickview, "fetch_docker_counters", lambda: {"containers_count": 2}
    )

    assert quickview._get_uptime() == "1h 10m"
    assert quickview._get_load() == (0.1, 0.2, 0.3)
    assert quickview._get_memory() == {"percent": 42.0}
    assert quickview._get_processes() == {"running": 1, "sleeping": 3}
    assert quickview._get_docker() == {"containers_count": 2}


def test_quickview_metric_collectors_handle_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(quickview, "psutil_adapter", _ExplodingAdapter())
    monkeypatch.setattr(
        quickview,
        "fetch_docker_counters",
        lambda: (_ for _ in ()).throw(RuntimeError("docker error")),
    )

    assert quickview._get_uptime() is None
    assert quickview._get_load() is None
    assert quickview._get_memory() is None
    assert quickview._get_processes() is None
    assert quickview._get_docker() is None


def test_collect_metrics_skips_none_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(quickview, "_get_uptime", lambda: "up")
    monkeypatch.setattr(quickview, "_get_load", lambda: (1.0, 2.0, 3.0))
    monkeypatch.setattr(quickview, "_get_memory", lambda: None)
    monkeypatch.setattr(quickview, "_get_processes", lambda: {"running": 2})
    monkeypatch.setattr(quickview, "_get_docker", lambda: None)

    collected = quickview._collect_metrics()
    assert collected["uptime"] == "up"
    assert collected["load_average"] == (1.0, 2.0, 3.0)
    assert collected["processes"] == {"running": 2}
    assert "memory" not in collected
    assert "docker" not in collected


def test_handle_quick_view_success(monkeypatch: pytest.MonkeyPatch) -> None:
    bot, actions, messages = _build_bot(monkeypatch)
    message = _build_message(10)

    monkeypatch.setattr(
        quickview,
        "_collect_metrics",
        lambda: {
            "uptime": "2h",
            "load_average": (0.2, 0.1, 0.05),
            "memory": {"percent": 10.5},
            "processes": {"running": 1},
            "docker": {"containers_count": 1, "images_count": 2},
        },
    )

    render_calls: dict[str, Any] = {}

    def _fake_render(template_name: str, **context: Any) -> str:
        render_calls["template_name"] = template_name
        render_calls["context"] = context
        return "quickview text"

    monkeypatch.setattr(quickview.Compiler, "quick_render", _fake_render)

    handler = cast(Callable[[Message, TeleBot], None], quickview.handle_quick_view)
    handler(message, bot)

    assert actions == [(10, "typing")]
    assert messages[-1]["text"] == "quickview text"
    assert messages[-1]["parse_mode"] == "Markdown"
    assert render_calls["template_name"] == "b_quick_view.jinja2"
    system_context = render_calls["context"]["context"]["system"]
    assert system_context["uptime"] == "2h"
    assert render_calls["context"]["context"]["docker"]["containers_count"] == 1


def test_handle_quick_view_no_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    bot, actions, messages = _build_bot(monkeypatch)
    message = _build_message(11)
    monkeypatch.setattr(quickview, "_collect_metrics", lambda: {})

    handler = cast(Callable[[Message, TeleBot], None], quickview.handle_quick_view)
    handler(message, bot)
    assert actions == [(11, "typing")]
    assert "Failed to get system metrics" in str(messages[-1]["text"])


def test_handle_quick_view_wraps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    bot, _actions, messages = _build_bot(monkeypatch)
    message = _build_message(12)
    monkeypatch.setattr(
        quickview,
        "_collect_metrics",
        lambda: {"uptime": "1h", "load_average": (0.1, 0.2, 0.3)},
    )
    monkeypatch.setattr(
        quickview.Compiler,
        "quick_render",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("render failed")),
    )

    with pytest.raises(HandlingException) as exc_info:
        handler = cast(Callable[[Message, TeleBot], None], quickview.handle_quick_view)
        handler(message, bot)

    assert exc_info.value.context.error_code == "HAND_QV1"
    assert "render failed" in str(exc_info.value.context.metadata["exception"])
    assert "An error occurred while processing the command." in str(
        messages[-1]["text"]
    )
