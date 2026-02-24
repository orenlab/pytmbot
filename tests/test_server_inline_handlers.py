from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import cast

import pytest
from telebot import TeleBot
from telebot.types import CallbackQuery

import pytmbot.handlers.server_handlers.inline.swap as swap_module
import pytmbot.handlers.server_handlers.inline.top_process as top_process_module
from pytmbot import exceptions


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
    callback_answers: list[dict[str, object]] = field(default_factory=list)
    edited_messages: list[dict[str, object]] = field(default_factory=list)

    def answer_callback_query(self, callback_query_id: str, **kwargs: object) -> bool:
        payload: dict[str, object] = {
            "callback_query_id": callback_query_id,
            **kwargs,
        }
        self.callback_answers.append(payload)
        return True

    def edit_message_text(self, **kwargs: object) -> str:
        self.edited_messages.append(kwargs)
        return "edited"


def _raw_handler(handler: object) -> Callable[[CallbackQuery, TeleBot], None]:
    wrapped = handler
    for _ in range(2):
        wrapped = getattr(wrapped, "__wrapped__", wrapped)
    return cast(Callable[[CallbackQuery, TeleBot], None], wrapped)


def _invoke(
    handler: Callable[[CallbackQuery, TeleBot], None],
    bot: _Bot,
    *,
    data: str,
) -> None:
    handler(cast(CallbackQuery, _Call(data=data)), cast(TeleBot, bot))


def _patch_auth_with_answer(
    monkeypatch: pytest.MonkeyPatch,
    module: object,
    *,
    text: str,
    result: tuple[bool, int | None],
) -> None:
    def _fake_auth(
        call: CallbackQuery, bot: TeleBot, **_kwargs: object
    ) -> tuple[bool, int | None]:
        callback_query_id = int(call.id) if str(call.id).isdigit() else 0
        bot.answer_callback_query(
            callback_query_id=callback_query_id,
            text=text,
            show_alert=True,
        )
        return result

    monkeypatch.setattr(module, "authorize_user_bound_callback", _fake_auth)


def _patch_auth_success(
    monkeypatch: pytest.MonkeyPatch, module: object, target_user_id: int = 17
) -> None:
    monkeypatch.setattr(
        module,
        "authorize_user_bound_callback",
        lambda call, bot, **kwargs: (True, target_user_id),
    )


def _assert_common_auth_paths(
    monkeypatch: pytest.MonkeyPatch,
    module: object,
    handler: Callable[[CallbackQuery, TeleBot], None],
    bot: _Bot,
    *,
    invalid_data: str,
    valid_data: str,
    invalid_text: str,
    denied_text: str,
    missing_text_fragment: str,
) -> None:
    _patch_auth_with_answer(
        monkeypatch,
        module,
        text=invalid_text,
        result=(False, None),
    )
    _invoke(handler, bot, data=invalid_data)
    assert invalid_text in str(bot.callback_answers[-1]["text"])

    _patch_auth_with_answer(
        monkeypatch,
        module,
        text=denied_text,
        result=(False, 17),
    )
    _invoke(handler, bot, data=valid_data)
    assert bot.callback_answers[-1]["text"] == denied_text

    _patch_auth_with_answer(
        monkeypatch,
        module,
        text=missing_text_fragment,
        result=(False, 17),
    )
    _invoke(handler, bot, data=valid_data)
    assert missing_text_fragment in str(bot.callback_answers[-1]["text"])


def _prepare_handler_with_auth_paths(
    monkeypatch: pytest.MonkeyPatch,
    *,
    module: object,
    handler_obj: object,
    invalid_data: str,
    valid_data: str,
    invalid_text: str,
    denied_text: str,
    missing_text_fragment: str,
) -> tuple[_Bot, Callable[[CallbackQuery, TeleBot], None]]:
    bot = _Bot()
    handler = _raw_handler(handler_obj)
    _assert_common_auth_paths(
        monkeypatch,
        module,
        handler,
        bot,
        invalid_data=invalid_data,
        valid_data=valid_data,
        invalid_text=invalid_text,
        denied_text=denied_text,
        missing_text_fragment=missing_text_fragment,
    )
    return bot, handler


def _patch_adapter_method(
    monkeypatch: pytest.MonkeyPatch,
    module: object,
    *,
    method_name: str,
    implementation: Callable[..., object],
) -> None:
    monkeypatch.setattr(
        module,
        "psutil_adapter",
        cast(
            object, type("_Adapter", (), {method_name: staticmethod(implementation)})()
        ),
    )


def test_handle_swap_info_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    bot, handler = _prepare_handler_with_auth_paths(
        monkeypatch,
        module=swap_module,
        handler_obj=swap_module.handle_swap_info,
        invalid_data="bad",
        valid_data="__swap_info__:17",
        invalid_text="Invalid swap request format.",
        denied_text="denied",
        missing_text_fragment="Cannot render swap info in this context.",
    )
    _patch_auth_success(monkeypatch, swap_module)
    _patch_adapter_method(
        monkeypatch,
        swap_module,
        method_name="get_swap_memory",
        implementation=lambda: None,
    )
    _invoke(handler, bot, data="__swap_info__:17")
    assert "can't get swap memory values" in str(bot.edited_messages[-1]["text"])

    _patch_adapter_method(
        monkeypatch,
        swap_module,
        method_name="get_swap_memory",
        implementation=lambda: {"used": "1 GiB"},
    )
    monkeypatch.setattr(
        swap_module.Compiler, "quick_render", lambda **kwargs: "swap-ok"
    )
    _invoke(handler, bot, data="__swap_info__:17")
    assert bot.edited_messages[-1]["text"] == "swap-ok"

    _patch_adapter_method(
        monkeypatch,
        swap_module,
        method_name="get_swap_memory",
        implementation=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(exceptions.HandlingException) as exc_info:
        _invoke(handler, bot, data="__swap_info__:17")
    assert exc_info.value.context.error_code == "HAND_009"


def test_handle_process_info_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    bot, handler = _prepare_handler_with_auth_paths(
        monkeypatch,
        module=top_process_module,
        handler_obj=top_process_module.handle_process_info,
        invalid_data="bad",
        valid_data="__process_info__:17",
        invalid_text="Invalid process info request format.",
        denied_text="denied",
        missing_text_fragment="Cannot render process info in this context.",
    )
    _patch_auth_success(monkeypatch, top_process_module)
    _patch_adapter_method(
        monkeypatch,
        top_process_module,
        method_name="get_top_processes",
        implementation=lambda count=10: [],
    )
    _invoke(handler, bot, data="__process_info__:17")
    assert (
        "can't get process information" in str(bot.edited_messages[-1]["text"]).lower()
    )

    _patch_adapter_method(
        monkeypatch,
        top_process_module,
        method_name="get_top_processes",
        implementation=lambda count=10: [
            {
                "pid": 100,
                "name": "super-long-process-name-that-will-be-shortened",
                "cpu_percent": 7.5,
                "memory_percent": 3.2,
            },
            {
                "pid": 200,
                "name": "python",
                "cpu_percent": 2.1,
                "memory_percent": 1.1,
            },
        ],
    )
    monkeypatch.setattr(
        top_process_module.Compiler,
        "quick_render",
        lambda template_name, context, **emojis: context["process_table"],
    )
    monkeypatch.setattr(top_process_module, "running_in_docker", True)
    _invoke(handler, bot, data="__process_info__:17")
    rendered_table = cast(str, bot.edited_messages[-1]["text"])
    assert "PID" in rendered_table
    assert "Process Name" in rendered_table
    assert bot.edited_messages[-1]["parse_mode"] == "HTML"

    _patch_adapter_method(
        monkeypatch,
        top_process_module,
        method_name="get_top_processes",
        implementation=lambda count=10: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(exceptions.HandlingException) as exc_info:
        _invoke(handler, bot, data="__process_info__:17")
    assert exc_info.value.context.error_code == "HAND_010"
