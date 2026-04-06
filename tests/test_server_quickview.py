from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import cast

import pytest
from telebot import TeleBot
from telebot.types import Message

import pytmbot.handlers.server_handlers.quickview as quickview
from pytmbot.exceptions import HandlingException
from pytmbot.parsers.compiler import Compiler
from tests._telebot_objects import telegram_object_from_payload
from tests._telebot_send_capture import build_bot_capture

type _PayloadScalar = str | int | float | bool | None
type _PayloadValue = _PayloadScalar | list["_PayloadValue"] | dict[str, "_PayloadValue"]
type _PayloadDict = dict[str, _PayloadValue]
type _RenderedMessage = dict[str, int | str | None]


def _exploding_adapter() -> SimpleNamespace:
    def fail(message: str) -> None:
        raise RuntimeError(message)

    return SimpleNamespace(
        get_uptime=lambda: fail("uptime error"),
        get_load_average=lambda: fail("load error"),
        get_memory=lambda: fail("memory error"),
        get_cpu_usage=lambda: fail("cpu error"),
        get_cpu_frequency=lambda: fail("cpu freq error"),
        get_cpu_count=lambda: fail("cpu count error"),
        get_process_counts=lambda: fail("proc error"),
    )


def _build_message(chat_id: int = 1) -> Message:
    payload: _PayloadDict = {
        "message_id": 1,
        "date": 1,
        "chat": {"id": chat_id, "type": "private"},
        "from": {"id": 101, "is_bot": False, "first_name": "Test"},
        "text": "quick view",
    }
    return telegram_object_from_payload(
        payload,
        parser=cast(Callable[[_PayloadDict], Message], Message.de_json),
        expected_type=Message,
    )


def test_quickview_metric_collectors_happy_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = SimpleNamespace(
        get_uptime=lambda: "1h 10m",
        get_load_average=lambda: (0.1, 0.2, 0.3),
        get_cpu_usage=lambda: {"cpu_percent": 5.0},
        get_cpu_frequency=lambda: {"current_freq": 2000.0},
        get_cpu_count=lambda: 8,
        get_memory=lambda: {"percent": 42.0},
        get_process_counts=lambda: {"running": 1, "sleeping": 3},
    )
    monkeypatch.setattr(quickview, "psutil_adapter", adapter)
    monkeypatch.setattr(
        quickview, "fetch_docker_counters", lambda: {"containers_count": 2}
    )

    assert quickview._get_uptime() == "1h 10m"
    assert quickview._get_load() == (0.1, 0.2, 0.3)
    assert quickview._get_cpu() == {
        "cpu_percent": 5.0,
        "cpu_count": 8,
        "physical_cpu_count": 8,
        "frequency_mhz": 2000.0,
    }
    assert quickview._get_memory() == {"percent": 42.0}
    assert quickview._get_processes() == {"running": 1, "sleeping": 3}
    assert quickview._get_docker() == {"containers_count": 2}


def test_quickview_metric_collectors_handle_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(quickview, "psutil_adapter", _exploding_adapter())
    monkeypatch.setattr(
        quickview,
        "fetch_docker_counters",
        lambda: (_ for _ in ()).throw(RuntimeError("docker error")),
    )

    assert quickview._get_uptime() is None
    assert quickview._get_load() is None
    assert quickview._get_cpu() is None
    assert quickview._get_memory() is None
    assert quickview._get_processes() is None
    assert quickview._get_docker() is None


def test_collect_metrics_skips_none_results(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(quickview, "_get_uptime", lambda: "up")
    monkeypatch.setattr(quickview, "_get_load", lambda: (1.0, 2.0, 3.0))
    monkeypatch.setattr(quickview, "_get_cpu", lambda: None)
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
    bot, actions, messages = build_bot_capture(monkeypatch)
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

    render_calls: _PayloadDict = {}

    def _fake_render(template_name: str, **context: _PayloadValue) -> str:
        render_calls["template_name"] = template_name
        render_calls["context"] = context
        return "quickview text"

    monkeypatch.setattr(Compiler, "quick_render", _fake_render)

    handler = cast(Callable[[Message, TeleBot], None], quickview.handle_quick_view)
    handler(message, bot)

    assert actions == [(10, "typing")]
    assert messages[-1]["text"] == "quickview text"
    assert messages[-1]["parse_mode"] == "Markdown"
    assert render_calls["template_name"] == "b_quick_view.jinja2"
    render_context = render_calls["context"]
    assert isinstance(render_context, dict)
    template_context = render_context.get("context")
    assert isinstance(template_context, dict)
    system_context = template_context.get("system")
    assert isinstance(system_context, dict)
    assert system_context["uptime"] == "2h"
    docker_context = template_context.get("docker")
    assert isinstance(docker_context, dict)
    assert docker_context["containers_count"] == 1


def test_handle_quick_view_no_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    bot, actions, messages = build_bot_capture(monkeypatch)
    message = _build_message(11)
    monkeypatch.setattr(quickview, "_collect_metrics", lambda: {})

    handler = cast(Callable[[Message, TeleBot], None], quickview.handle_quick_view)
    handler(message, bot)
    assert actions == [(11, "typing")]
    assert "Failed to get system metrics" in str(messages[-1]["text"])


def test_handle_quick_view_wraps_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    bot, _actions, messages = build_bot_capture(monkeypatch)
    message = _build_message(12)
    monkeypatch.setattr(
        quickview,
        "_collect_metrics",
        lambda: {"uptime": "1h", "load_average": (0.1, 0.2, 0.3)},
    )
    monkeypatch.setattr(
        Compiler,
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
