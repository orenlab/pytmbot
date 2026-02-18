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


def _assert_memory_or_process_handler_paths(
    *,
    monkeypatch: pytest.MonkeyPatch,
    module: object,
    compiler: object,
    handler: object,
    adapter_method: str,
    success_payload: object,
    success_text: str,
    expected_error_code: str,
    message: Message,
    bot: TeleBot,
    messages: list[dict[str, object]],
) -> None:
    monkeypatch.setattr(
        module,
        "psutil_adapter",
        type("A", (), {adapter_method: lambda self: success_payload})(),
    )
    monkeypatch.setattr(
        module,
        "button_data",
        lambda text, callback_data: {"text": text, "callback_data": callback_data},
    )
    monkeypatch.setattr(
        module,
        "keyboards",
        type("K", (), {"build_inline_keyboard": lambda self, data: {"inline": data}})(),
    )
    monkeypatch.setattr(compiler, "quick_render", lambda **_kwargs: success_text)
    _invoke_handler(handler, message, bot)
    assert messages[-1]["text"] == success_text
    assert messages[-1]["parse_mode"] == "HTML"
    reply_markup = messages[-1]["reply_markup"]
    assert isinstance(reply_markup, dict)
    assert str(reply_markup["inline"]["callback_data"]).endswith(":777")

    monkeypatch.setattr(
        module,
        "psutil_adapter",
        type("A", (), {adapter_method: lambda self: None})(),
    )
    _invoke_handler(handler, message, bot)
    assert "Some error occurred" in str(messages[-1]["text"])

    monkeypatch.setattr(
        module,
        "psutil_adapter",
        type(
            "A",
            (),
            {
                adapter_method: lambda self: (_ for _ in ()).throw(
                    RuntimeError("handler fail")
                )
            },
        )(),
    )
    with pytest.raises(HandlingException) as exc_info:
        _invoke_handler(handler, message, bot)
    assert exc_info.value.context.error_code == expected_error_code


def _assert_simple_handler_paths(
    *,
    monkeypatch: pytest.MonkeyPatch,
    module: object,
    compiler: object,
    handler: object,
    adapter_method: str,
    success_payload: object,
    success_text: str,
    parse_mode: str,
    none_text_contains: str,
    expected_error_code: str,
    message: Message,
    bot: TeleBot,
    messages: list[dict[str, object]],
) -> None:
    monkeypatch.setattr(
        module,
        "psutil_adapter",
        type("A", (), {adapter_method: lambda self: success_payload})(),
    )
    monkeypatch.setattr(compiler, "quick_render", lambda **_kwargs: success_text)
    _invoke_handler(handler, message, bot)
    assert messages[-1]["text"] == success_text
    assert messages[-1]["parse_mode"] == parse_mode

    monkeypatch.setattr(
        module,
        "psutil_adapter",
        type("A", (), {adapter_method: lambda self: None})(),
    )
    _invoke_handler(handler, message, bot)
    assert none_text_contains in str(messages[-1]["text"])

    monkeypatch.setattr(
        module,
        "psutil_adapter",
        type(
            "A",
            (),
            {
                adapter_method: lambda self: (_ for _ in ()).throw(
                    RuntimeError("handler fail")
                )
            },
        )(),
    )
    with pytest.raises(HandlingException) as exc_info:
        _invoke_handler(handler, message, bot)
    assert exc_info.value.context.error_code == expected_error_code


def test_handle_uptime_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    bot, actions, messages = _build_bot(monkeypatch)
    message = _build_message(10)

    monkeypatch.setattr(
        uptime_module,
        "psutil_adapter",
        type("A", (), {"get_uptime": lambda self: "1h"})(),
    )
    monkeypatch.setattr(
        uptime_module.Compiler, "quick_render", lambda **_kwargs: "uptime ok"
    )
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
        type(
            "A",
            (),
            {"get_uptime": lambda self: (_ for _ in ()).throw(RuntimeError("boom"))},
        )(),
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
    monkeypatch.setattr(
        load_average_module.Compiler,
        "quick_render",
        lambda *_args, **_kwargs: "load ok",
    )
    _invoke_handler(load_average_module.handle_load_average, message, bot)
    assert messages[-1]["text"] == "load ok"
    assert messages[-1]["parse_mode"] == "Markdown"

    monkeypatch.setattr(
        load_average_module,
        "psutil_adapter",
        type(
            "A",
            (),
            {
                "get_load_average": lambda self: (_ for _ in ()).throw(
                    RuntimeError("load fail")
                )
            },
        )(),
    )
    with pytest.raises(HandlingException) as exc_info:
        _invoke_handler(load_average_module.handle_load_average, message, bot)
    assert exc_info.value.context.error_code == "HAND_007"


def test_handle_network_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    bot, _actions, messages = _build_bot(monkeypatch)
    message = _build_message(12)

    _assert_simple_handler_paths(
        monkeypatch=monkeypatch,
        module=network_module,
        compiler=network_module.Compiler,
        handler=network_module.handle_network,
        adapter_method="get_net_io_counters",
        success_payload={"rx": "1 MiB"},
        success_text="network ok",
        parse_mode="HTML",
        none_text_contains="error occurred while getting network statistics",
        expected_error_code="HAND_005",
        message=message,
        bot=bot,
        messages=messages,
    )


def test_handle_memory_and_process_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    bot, _actions, messages = _build_bot(monkeypatch)
    message = _build_message(13, user_id=777)

    _assert_memory_or_process_handler_paths(
        monkeypatch=monkeypatch,
        module=memory_module,
        compiler=memory_module.Compiler,
        handler=memory_module.handle_memory,
        adapter_method="get_memory",
        success_payload={"percent": 25.0},
        success_text="memory ok",
        expected_error_code="HAND_006",
        message=message,
        bot=bot,
        messages=messages,
    )
    _assert_memory_or_process_handler_paths(
        monkeypatch=monkeypatch,
        module=process_module,
        compiler=process_module.Compiler,
        handler=process_module.handle_process,
        adapter_method="get_process_counts",
        success_payload={"running": 3},
        success_text="process ok",
        expected_error_code="HAND_004",
        message=message,
        bot=bot,
        messages=messages,
    )


def test_handle_sensors_and_filesystem_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    bot, _actions, messages = _build_bot(monkeypatch)
    message = _build_message(14)

    _assert_simple_handler_paths(
        monkeypatch=monkeypatch,
        module=sensors_module,
        compiler=sensors_module.Compiler,
        handler=sensors_module.handle_sensors,
        adapter_method="get_sensors_temperatures",
        success_payload=[{"name": "cpu", "temp": 55}],
        success_text="sensors ok",
        parse_mode="HTML",
        none_text_contains="No sensors were found",
        expected_error_code="HAND_003",
        message=message,
        bot=bot,
        messages=messages,
    )
    _assert_simple_handler_paths(
        monkeypatch=monkeypatch,
        module=filesystem_module,
        compiler=filesystem_module.Compiler,
        handler=filesystem_module.handle_file_system,
        adapter_method="get_disk_usage",
        success_payload={"disk": []},
        success_text="fs ok",
        parse_mode="HTML",
        none_text_contains="Failed to handle disk usage",
        expected_error_code="HAND_008",
        message=message,
        bot=bot,
        messages=messages,
    )
