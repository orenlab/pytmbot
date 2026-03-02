from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Never, cast

import pytest
from telebot import TeleBot
from telebot.types import CallbackQuery

import pytmbot.handlers.server_handlers.inline.system_views as system_views_module
from pytmbot import exceptions
from pytmbot.handlers.server_handlers.cpu import CPU_INFO_PREFIX, CPU_PER_CORE_PREFIX
from pytmbot.handlers.server_handlers.filesystem import DISK_IO_PREFIX
from pytmbot.handlers.server_handlers.network import (
    NETWORK_CONNECTIONS_PREFIX,
    NETWORK_OVERVIEW_PREFIX,
)
from pytmbot.handlers.server_handlers.sensors import FAN_SPEEDS_PREFIX
from pytmbot.parsers.compiler import Compiler

type _PayloadValue = (
    str | int | float | bool | None | dict[str, _PayloadValue] | list[_PayloadValue]
)
type _PayloadDict = dict[str, _PayloadValue]
type _CallbackHandler = Callable[[CallbackQuery, TeleBot], None]
type _RawHandlerInput = (
    Callable[..., None] | Callable[[Callable[..., None]], Callable[..., None]]
)
type _HandlerCase = tuple[_RawHandlerInput, str, str]


@dataclass
class _User:
    id: int = 17


@dataclass
class _Chat:
    id: int = 27


@dataclass
class _Message:
    chat: _Chat = field(default_factory=_Chat)
    message_id: int = 37


@dataclass
class _Call:
    id: str = "cb-id"
    data: str | None = "payload"
    from_user: _User | None = field(default_factory=_User)
    message: _Message | None = field(default_factory=_Message)


@dataclass
class _Bot:
    callback_answers: list[_PayloadDict] = field(default_factory=list)
    edited_messages: list[_PayloadDict] = field(default_factory=list)

    def answer_callback_query(
        self, callback_query_id: str, **kwargs: _PayloadValue
    ) -> bool:
        payload: _PayloadDict = {
            "callback_query_id": callback_query_id,
            **kwargs,
        }
        self.callback_answers.append(payload)
        return True

    def edit_message_text(self, **kwargs: _PayloadValue) -> str:
        self.edited_messages.append(kwargs)
        return "edited"


def _raw_handler(handler: _RawHandlerInput) -> _CallbackHandler:
    wrapped = handler
    for _ in range(3):
        wrapped = getattr(wrapped, "__wrapped__", wrapped)
    return cast(_CallbackHandler, wrapped)


def _raise_runtime_error(message: str = "boom") -> Never:
    raise RuntimeError(message)


def _patch_common_success(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        system_views_module,
        "em",
        SimpleNamespace(get_emoji=lambda key: key),
    )
    monkeypatch.setattr(
        system_views_module,
        "_resolve_target_user_id",
        lambda call, bot, **kwargs: (True, 17),
    )
    monkeypatch.setattr(
        system_views_module,
        "psutil_adapter",
        SimpleNamespace(
            get_cpu_usage=lambda: {"cpu_percent_per_core": [12.0, 34.0]},
            get_cpu_times_percent=lambda: {"user": 10.0, "system": 5.0},
            get_net_io_counters=lambda: {"bytes_sent": "1 MiB"},
            get_net_interface_stats=lambda: {
                "eth0": {
                    "speed": 1000,
                    "is_up": True,
                    "mtu": 1500,
                    "ip_address": "10.0.0.2",
                }
            },
            get_network_connections_summary=lambda: {"ESTABLISHED": 3},
            get_disk_usage=lambda: {"used": "1 GiB"},
            get_disk_io_stats=lambda: [{"name": "sda", "read_bytes": "1 MiB"}],
            get_users_info=lambda: [
                {
                    "username": "root",
                    "terminal": "pts/0",
                    "host": "127.0.0.1",
                    "started": 0.0,
                }
            ],
            get_sensors_temperatures=lambda: {"cpu": [{"label": "pkg", "current": 45}]},
            get_fan_speeds=lambda: [{"name": "fan0", "rpm": 900}],
            get_memory=lambda: {"memory_percent": 20.0},
        ),
    )
    monkeypatch.setattr(
        system_views_module,
        "_build_cpu_overview_context",
        lambda: {"cpu_percent": 15.0},
    )
    monkeypatch.setattr(
        system_views_module, "_build_cpu_keyboard", lambda user_id: "kbd"
    )
    monkeypatch.setattr(
        system_views_module, "_build_cpu_detail_keyboard", lambda user_id: "kbd"
    )
    monkeypatch.setattr(
        system_views_module, "_build_network_keyboard", lambda user_id: "kbd"
    )
    monkeypatch.setattr(
        system_views_module, "_build_network_detail_keyboard", lambda user_id: "kbd"
    )
    monkeypatch.setattr(
        system_views_module, "_build_filesystem_keyboard", lambda user_id: "kbd"
    )
    monkeypatch.setattr(
        system_views_module, "_build_filesystem_detail_keyboard", lambda user_id: "kbd"
    )
    monkeypatch.setattr(
        system_views_module, "_build_uptime_keyboard", lambda user_id: "kbd"
    )
    monkeypatch.setattr(
        system_views_module, "_build_sensors_keyboard", lambda user_id: "kbd"
    )
    monkeypatch.setattr(
        system_views_module,
        "_build_sensors_detail_keyboard",
        lambda user_id, show_fans_button: "kbd",
    )
    monkeypatch.setattr(
        system_views_module,
        "_build_quickview_keyboard",
        lambda user_id, on_overview: "kbd",
    )
    monkeypatch.setattr(system_views_module, "_collect_metrics", lambda: {"cpu": 5.0})
    monkeypatch.setattr(
        system_views_module,
        "_build_quickview_context",
        lambda metrics: {"metrics": metrics},
    )
    monkeypatch.setattr(system_views_module, "set_naturaltime", lambda dt: "now")
    monkeypatch.setattr(
        Compiler,
        "quick_render",
        lambda **kwargs: f"{kwargs['template_name']}-ok",
    )


_HANDLER_CASES: tuple[_HandlerCase, ...] = (
    (system_views_module.handle_cpu_info, "HAND_CPU_002", "HTML"),
    (system_views_module.handle_cpu_per_core, "HAND_CPU_003", "HTML"),
    (system_views_module.handle_cpu_times, "HAND_CPU_004", "HTML"),
    (system_views_module.handle_network_overview, "HAND_NET_001", "HTML"),
    (system_views_module.handle_network_interfaces, "HAND_NET_002", "HTML"),
    (system_views_module.handle_network_connections, "HAND_NET_003", "HTML"),
    (system_views_module.handle_filesystem_overview, "HAND_FS_001", "HTML"),
    (system_views_module.handle_disk_io, "HAND_FS_002", "HTML"),
    (system_views_module.handle_users_info, "HAND_UP_001", "HTML"),
    (system_views_module.handle_sensors_overview, "HAND_SENS_001", "HTML"),
    (system_views_module.handle_fan_speeds, "HAND_SENS_002", "HTML"),
    (system_views_module.handle_quickview_overview, "HAND_QV2", "Markdown"),
    (system_views_module.handle_quickview_memory, "HAND_QV3", "HTML"),
    (system_views_module.handle_quickview_sensors, "HAND_QV4", "HTML"),
    (system_views_module.handle_quickview_cpu, "HAND_QV5", "HTML"),
    (system_views_module.handle_quickview_disk, "HAND_QV6", "HTML"),
)


@pytest.mark.parametrize(("handler_obj", "_error_code", "parse_mode"), _HANDLER_CASES)
def test_system_views_handlers_route_via_shared_edit(
    monkeypatch: pytest.MonkeyPatch,
    handler_obj: _RawHandlerInput,
    _error_code: str,
    parse_mode: str,
) -> None:
    _patch_common_success(monkeypatch)
    edit_calls: list[_PayloadDict] = []
    monkeypatch.setattr(
        system_views_module,
        "_edit_message",
        lambda call, bot, **kwargs: edit_calls.append(kwargs),
    )

    handler = _raw_handler(handler_obj)
    handler(cast(CallbackQuery, _Call()), cast(TeleBot, _Bot()))

    assert edit_calls
    assert edit_calls[-1]["parse_mode"] == parse_mode


@pytest.mark.parametrize(("handler_obj", "_error_code", "_parse_mode"), _HANDLER_CASES)
def test_system_views_handlers_return_without_edit_when_not_allowed(
    monkeypatch: pytest.MonkeyPatch,
    handler_obj: _RawHandlerInput,
    _error_code: str,
    _parse_mode: str,
) -> None:
    _patch_common_success(monkeypatch)
    monkeypatch.setattr(
        system_views_module,
        "_resolve_target_user_id",
        lambda call, bot, **kwargs: (False, None),
    )
    edit_calls: list[_PayloadDict] = []
    monkeypatch.setattr(
        system_views_module,
        "_edit_message",
        lambda call, bot, **kwargs: edit_calls.append(kwargs),
    )

    handler = _raw_handler(handler_obj)
    handler(cast(CallbackQuery, _Call()), cast(TeleBot, _Bot()))
    assert edit_calls == []


@pytest.mark.parametrize(("handler_obj", "_error_code", "_parse_mode"), _HANDLER_CASES)
def test_system_views_handlers_return_without_edit_when_message_missing(
    monkeypatch: pytest.MonkeyPatch,
    handler_obj: _RawHandlerInput,
    _error_code: str,
    _parse_mode: str,
) -> None:
    _patch_common_success(monkeypatch)
    edit_calls: list[_PayloadDict] = []
    monkeypatch.setattr(
        system_views_module,
        "_edit_message",
        lambda call, bot, **kwargs: edit_calls.append(kwargs),
    )

    handler = _raw_handler(handler_obj)
    handler(cast(CallbackQuery, _Call(message=None)), cast(TeleBot, _Bot()))
    assert edit_calls == []


@pytest.mark.parametrize(("handler_obj", "error_code", "_parse_mode"), _HANDLER_CASES)
def test_system_views_handlers_wrap_exceptions(
    monkeypatch: pytest.MonkeyPatch,
    handler_obj: _RawHandlerInput,
    error_code: str,
    _parse_mode: str,
) -> None:
    _patch_common_success(monkeypatch)
    monkeypatch.setattr(
        Compiler,
        "quick_render",
        lambda **kwargs: _raise_runtime_error("render-failed"),
    )

    handler = _raw_handler(handler_obj)
    with pytest.raises(exceptions.HandlingException) as exc_info:
        handler(cast(CallbackQuery, _Call()), cast(TeleBot, _Bot()))
    assert exc_info.value.context.error_code == error_code


def test_progress_bar_clamps_values() -> None:
    assert system_views_module._progress_bar(-10, width=6) == "░░░░░░"
    assert system_views_module._progress_bar(50, width=6) == "▓▓▓░░░"
    assert system_views_module._progress_bar(170, width=6) == "▓▓▓▓▓▓"


def test_resolve_target_user_id_wraps_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        system_views_module,
        "authorize_user_bound_callback",
        lambda call, bot, **kwargs: (False, None),
    )
    is_allowed, user_id = system_views_module._resolve_target_user_id(
        cast(CallbackQuery, _Call()),
        cast(TeleBot, _Bot()),
        prefix="__x__",
        invalid_payload_text="bad",
        missing_message_text="missing",
    )
    assert is_allowed is False
    assert user_id is None

    monkeypatch.setattr(
        system_views_module,
        "authorize_user_bound_callback",
        lambda call, bot, **kwargs: (True, 42),
    )
    is_allowed_ok, user_id_ok = system_views_module._resolve_target_user_id(
        cast(CallbackQuery, _Call()),
        cast(TeleBot, _Bot()),
        prefix="__x__",
        invalid_payload_text="bad",
        missing_message_text="missing",
    )
    assert is_allowed_ok is True
    assert user_id_ok == 42


def test_keyboard_builders_include_expected_callbacks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        system_views_module,
        "button_data",
        lambda text, callback_data: {"text": text, "callback_data": callback_data},
    )
    monkeypatch.setattr(
        system_views_module,
        "keyboards",
        SimpleNamespace(build_inline_keyboard=lambda buttons: buttons),
    )

    cpu_buttons = cast(
        list[dict[str, str]], system_views_module._build_cpu_detail_keyboard(17)
    )
    cpu_callbacks = [button["callback_data"] for button in cpu_buttons]
    assert any(value.startswith(CPU_INFO_PREFIX) for value in cpu_callbacks)
    assert any(value.startswith(CPU_PER_CORE_PREFIX) for value in cpu_callbacks)

    net_buttons = cast(
        list[dict[str, str]], system_views_module._build_network_detail_keyboard(17)
    )
    net_callbacks = [button["callback_data"] for button in net_buttons]
    assert any(value.startswith(NETWORK_OVERVIEW_PREFIX) for value in net_callbacks)
    assert any(value.startswith(NETWORK_CONNECTIONS_PREFIX) for value in net_callbacks)

    fs_buttons = cast(
        list[dict[str, str]], system_views_module._build_filesystem_detail_keyboard(17)
    )
    assert any(
        button["callback_data"].startswith(DISK_IO_PREFIX) for button in fs_buttons
    )

    sensors_buttons = cast(
        list[dict[str, str]],
        system_views_module._build_sensors_detail_keyboard(17, show_fans_button=True),
    )
    assert any(
        button["callback_data"].startswith(FAN_SPEEDS_PREFIX)
        for button in sensors_buttons
    )


def test_handle_sensors_overview_uses_fallback_without_temperatures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_common_success(monkeypatch)
    monkeypatch.setattr(
        system_views_module,
        "psutil_adapter",
        SimpleNamespace(
            get_sensors_temperatures=lambda: {},
            get_fan_speeds=lambda: [],
        ),
    )
    edit_calls: list[_PayloadDict] = []
    monkeypatch.setattr(
        system_views_module,
        "_edit_message",
        lambda call, bot, **kwargs: edit_calls.append(kwargs),
    )

    handler = _raw_handler(system_views_module.handle_sensors_overview)
    handler(cast(CallbackQuery, _Call()), cast(TeleBot, _Bot()))
    assert "No temperature sensors available." in str(edit_calls[-1]["text"])
    assert edit_calls[-1]["reply_markup"] is None


def test_handle_quickview_sensors_uses_fallback_without_temperatures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_common_success(monkeypatch)
    monkeypatch.setattr(
        system_views_module,
        "psutil_adapter",
        SimpleNamespace(get_sensors_temperatures=lambda: {}),
    )
    edit_calls: list[_PayloadDict] = []
    monkeypatch.setattr(
        system_views_module,
        "_edit_message",
        lambda call, bot, **kwargs: edit_calls.append(kwargs),
    )

    handler = _raw_handler(system_views_module.handle_quickview_sensors)
    handler(cast(CallbackQuery, _Call()), cast(TeleBot, _Bot()))
    assert edit_calls[-1]["text"] == "⚠️ No sensors were found :("
