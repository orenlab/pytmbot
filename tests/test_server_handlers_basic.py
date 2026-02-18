from __future__ import annotations

from collections.abc import Callable
from typing import cast

import pytest
from telebot import TeleBot
from telebot.types import Message

import pytmbot.handlers.server_handlers.filesystem as filesystem_module
import pytmbot.handlers.server_handlers.load_average as load_average_module
import pytmbot.handlers.server_handlers.memory as memory_module
import pytmbot.handlers.server_handlers.network as network_module
import pytmbot.handlers.server_handlers.process as process_module
import pytmbot.handlers.server_handlers.sensors as sensors_module
import pytmbot.handlers.server_handlers.uptime as uptime_module
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
        reply_markup: object | None = None,
        **kwargs: object,
    ) -> dict[str, object]:
        del kwargs
        payload = {
            "chat_id": int(chat_id),
            "text": text,
            "parse_mode": parse_mode,
            "reply_markup": reply_markup,
        }
        messages.append(payload)
        return payload

    monkeypatch.setattr(bot, "send_chat_action", _send_chat_action)
    monkeypatch.setattr(bot, "send_message", _send_message)
    return bot, actions, messages


def _build_message(chat_id: int = 1, user_id: int = 101) -> Message:
    payload = {
        "message_id": 1,
        "date": 1,
        "chat": {"id": chat_id, "type": "private"},
        "from": {"id": user_id, "is_bot": False, "first_name": "Test"},
        "text": "command",
    }
    message_obj = Message.de_json(payload)
    if not isinstance(message_obj, Message):
        raise AssertionError("Expected Message instance")
    return message_obj


def _invoke_handler(
    handler: object,
    message: Message,
    bot: TeleBot,
) -> None:
    typed_handler = cast(Callable[[Message, TeleBot], None], handler)
    typed_handler(message, bot)


def test_handle_uptime_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    bot, actions, messages = _build_bot(monkeypatch)
    message = _build_message(10)

    monkeypatch.setattr(uptime_module, "psutil_adapter", type("A", (), {"get_uptime": lambda self: "1h"})())
    monkeypatch.setattr(uptime_module.Compiler, "quick_render", lambda **_kwargs: "uptime ok")
    _invoke_handler(uptime_module.handle_uptime, message, bot)
    assert actions[-1] == (10, "typing")
    assert messages[-1]["text"] == "uptime ok"

    monkeypatch.setattr(
        uptime_module,
        "psutil_adapter",
        type("A", (), {"get_uptime": lambda self: None})(),
    )
    _invoke_handler(uptime_module.handle_uptime, message, bot)
    assert "Some error occurred" in str(messages[-1]["text"])

    monkeypatch.setattr(
        uptime_module,
        "psutil_adapter",
        type("A", (), {"get_uptime": lambda self: (_ for _ in ()).throw(RuntimeError("boom"))})(),
    )
    with pytest.raises(HandlingException) as exc_info:
        _invoke_handler(uptime_module.handle_uptime, message, bot)
    assert exc_info.value.context.error_code == "HAND_001"


def test_handle_load_average_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    bot, _actions, messages = _build_bot(monkeypatch)
    message = _build_message(11)

    monkeypatch.setattr(
        load_average_module,
        "psutil_adapter",
        type("A", (), {"get_load_average": lambda self: (0.1, 0.2, 0.3)})(),
    )
    monkeypatch.setattr(load_average_module.Compiler, "quick_render", lambda *_args, **_kwargs: "load ok")
    _invoke_handler(load_average_module.handle_load_average, message, bot)
    assert messages[-1]["text"] == "load ok"
    assert messages[-1]["parse_mode"] == "Markdown"

    monkeypatch.setattr(
        load_average_module,
        "psutil_adapter",
        type("A", (), {"get_load_average": lambda self: (_ for _ in ()).throw(RuntimeError("load fail"))})(),
    )
    with pytest.raises(HandlingException) as exc_info:
        _invoke_handler(load_average_module.handle_load_average, message, bot)
    assert exc_info.value.context.error_code == "HAND_007"


def test_handle_network_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    bot, _actions, messages = _build_bot(monkeypatch)
    message = _build_message(12)

    monkeypatch.setattr(
        network_module,
        "psutil_adapter",
        type("A", (), {"get_net_io_counters": lambda self: {"rx": "1 MiB"}})(),
    )
    monkeypatch.setattr(network_module.Compiler, "quick_render", lambda **_kwargs: "network ok")
    _invoke_handler(network_module.handle_network, message, bot)
    assert messages[-1]["text"] == "network ok"
    assert messages[-1]["parse_mode"] == "HTML"

    monkeypatch.setattr(
        network_module,
        "psutil_adapter",
        type("A", (), {"get_net_io_counters": lambda self: None})(),
    )
    _invoke_handler(network_module.handle_network, message, bot)
    assert "error occurred while getting network statistics" in str(messages[-1]["text"])

    monkeypatch.setattr(
        network_module,
        "psutil_adapter",
        type("A", (), {"get_net_io_counters": lambda self: (_ for _ in ()).throw(RuntimeError("net fail"))})(),
    )
    with pytest.raises(HandlingException) as exc_info:
        _invoke_handler(network_module.handle_network, message, bot)
    assert exc_info.value.context.error_code == "HAND_005"


def test_handle_memory_and_process_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    bot, _actions, messages = _build_bot(monkeypatch)
    message = _build_message(13, user_id=777)

    # Memory handler
    monkeypatch.setattr(
        memory_module,
        "psutil_adapter",
        type("A", (), {"get_memory": lambda self: {"percent": 25.0}})(),
    )
    monkeypatch.setattr(memory_module, "button_data", lambda text, callback_data: {"text": text, "callback_data": callback_data})
    monkeypatch.setattr(memory_module, "keyboards", type("K", (), {"build_inline_keyboard": lambda self, data: {"inline": data}})())
    monkeypatch.setattr(memory_module.Compiler, "quick_render", lambda **_kwargs: "memory ok")
    _invoke_handler(memory_module.handle_memory, message, bot)
    assert messages[-1]["text"] == "memory ok"
    assert messages[-1]["parse_mode"] == "HTML"
    reply_markup = messages[-1]["reply_markup"]
    assert isinstance(reply_markup, dict)
    assert str(reply_markup["inline"]["callback_data"]).endswith(":777")

    monkeypatch.setattr(
        memory_module,
        "psutil_adapter",
        type("A", (), {"get_memory": lambda self: None})(),
    )
    _invoke_handler(memory_module.handle_memory, message, bot)
    assert "Some error occurred" in str(messages[-1]["text"])

    monkeypatch.setattr(
        memory_module,
        "psutil_adapter",
        type("A", (), {"get_memory": lambda self: (_ for _ in ()).throw(RuntimeError("mem fail"))})(),
    )
    with pytest.raises(HandlingException) as mem_exc:
        _invoke_handler(memory_module.handle_memory, message, bot)
    assert mem_exc.value.context.error_code == "HAND_006"

    # Process handler
    monkeypatch.setattr(
        process_module,
        "psutil_adapter",
        type("A", (), {"get_process_counts": lambda self: {"running": 3}})(),
    )
    monkeypatch.setattr(process_module, "button_data", lambda text, callback_data: {"text": text, "callback_data": callback_data})
    monkeypatch.setattr(process_module, "keyboards", type("K", (), {"build_inline_keyboard": lambda self, data: {"inline": data}})())
    monkeypatch.setattr(process_module.Compiler, "quick_render", lambda **_kwargs: "process ok")
    _invoke_handler(process_module.handle_process, message, bot)
    assert messages[-1]["text"] == "process ok"
    process_markup = messages[-1]["reply_markup"]
    assert isinstance(process_markup, dict)
    assert str(process_markup["inline"]["callback_data"]).endswith(":777")

    monkeypatch.setattr(
        process_module,
        "psutil_adapter",
        type("A", (), {"get_process_counts": lambda self: None})(),
    )
    _invoke_handler(process_module.handle_process, message, bot)
    assert "Some error occurred" in str(messages[-1]["text"])

    monkeypatch.setattr(
        process_module,
        "psutil_adapter",
        type("A", (), {"get_process_counts": lambda self: (_ for _ in ()).throw(RuntimeError("proc fail"))})(),
    )
    with pytest.raises(HandlingException) as proc_exc:
        _invoke_handler(process_module.handle_process, message, bot)
    assert proc_exc.value.context.error_code == "HAND_004"


def test_handle_sensors_and_filesystem_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    bot, _actions, messages = _build_bot(monkeypatch)
    message = _build_message(14)

    monkeypatch.setattr(
        sensors_module,
        "psutil_adapter",
        type("A", (), {"get_sensors_temperatures": lambda self: [{"name": "cpu", "temp": 55}]})(),
    )
    monkeypatch.setattr(sensors_module.Compiler, "quick_render", lambda **_kwargs: "sensors ok")
    _invoke_handler(sensors_module.handle_sensors, message, bot)
    assert messages[-1]["text"] == "sensors ok"
    assert messages[-1]["parse_mode"] == "HTML"

    monkeypatch.setattr(
        sensors_module,
        "psutil_adapter",
        type("A", (), {"get_sensors_temperatures": lambda self: []})(),
    )
    _invoke_handler(sensors_module.handle_sensors, message, bot)
    assert "No sensors were found" in str(messages[-1]["text"])

    monkeypatch.setattr(
        sensors_module,
        "psutil_adapter",
        type("A", (), {"get_sensors_temperatures": lambda self: (_ for _ in ()).throw(RuntimeError("sensor fail"))})(),
    )
    with pytest.raises(HandlingException) as sens_exc:
        _invoke_handler(sensors_module.handle_sensors, message, bot)
    assert sens_exc.value.context.error_code == "HAND_003"

    monkeypatch.setattr(
        filesystem_module,
        "psutil_adapter",
        type("A", (), {"get_disk_usage": lambda self: {"disk": []}})(),
    )
    monkeypatch.setattr(filesystem_module.Compiler, "quick_render", lambda **_kwargs: "fs ok")
    _invoke_handler(filesystem_module.handle_file_system, message, bot)
    assert messages[-1]["text"] == "fs ok"
    assert messages[-1]["parse_mode"] == "HTML"

    monkeypatch.setattr(
        filesystem_module,
        "psutil_adapter",
        type("A", (), {"get_disk_usage": lambda self: None})(),
    )
    _invoke_handler(filesystem_module.handle_file_system, message, bot)
    assert "Failed to handle disk usage" in str(messages[-1]["text"])

    monkeypatch.setattr(
        filesystem_module,
        "psutil_adapter",
        type("A", (), {"get_disk_usage": lambda self: (_ for _ in ()).throw(RuntimeError("fs fail"))})(),
    )
    with pytest.raises(HandlingException) as fs_exc:
        _invoke_handler(filesystem_module.handle_file_system, message, bot)
    assert fs_exc.value.context.error_code == "HAND_008"
