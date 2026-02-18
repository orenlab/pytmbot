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
from tests._callback_path_helpers import assert_standard_callback_auth_paths


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


def test_handle_swap_info_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = _Bot()
    handler = _raw_handler(swap_module.handle_swap_info)

    assert_standard_callback_auth_paths(
        monkeypatch=monkeypatch,
        module=swap_module,
        handler=cast(Callable[[CallbackQuery, TeleBot], object], handler),
        bot=bot,
        call_builder=lambda **kwargs: cast(CallbackQuery, _Call(**kwargs)),
        invalid_data="bad",
        valid_data="__swap_info__:17",
        target_user_id=17,
        invalid_text_contains="Invalid swap request format",
        denied_text="denied",
        missing_message_text_contains="Cannot render swap info",
    )

    monkeypatch.setattr(
        swap_module,
        "psutil_adapter",
        cast(object, type("_A", (), {"get_swap_memory": staticmethod(lambda: None)})()),
    )
    handler(cast(CallbackQuery, _Call(data="__swap_info__:17")), cast(TeleBot, bot))
    assert "can't get swap memory values" in str(bot.edited_messages[-1]["text"])

    monkeypatch.setattr(
        swap_module,
        "psutil_adapter",
        cast(
            object,
            type(
                "_A2", (), {"get_swap_memory": staticmethod(lambda: {"used": "1 GiB"})}
            )(),
        ),
    )
    monkeypatch.setattr(
        swap_module.Compiler, "quick_render", lambda **kwargs: "swap-ok"
    )
    handler(cast(CallbackQuery, _Call(data="__swap_info__:17")), cast(TeleBot, bot))
    assert bot.edited_messages[-1]["text"] == "swap-ok"

    monkeypatch.setattr(
        swap_module,
        "psutil_adapter",
        cast(
            object,
            type(
                "_A3",
                (),
                {
                    "get_swap_memory": staticmethod(
                        lambda: (_ for _ in ()).throw(RuntimeError("boom"))
                    )
                },
            )(),
        ),
    )
    with pytest.raises(exceptions.HandlingException) as exc_info:
        handler(cast(CallbackQuery, _Call(data="__swap_info__:17")), cast(TeleBot, bot))
    assert exc_info.value.context.error_code == "HAND_009"


def test_handle_process_info_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = _Bot()
    handler = _raw_handler(top_process_module.handle_process_info)

    assert_standard_callback_auth_paths(
        monkeypatch=monkeypatch,
        module=top_process_module,
        handler=cast(Callable[[CallbackQuery, TeleBot], object], handler),
        bot=bot,
        call_builder=lambda **kwargs: cast(CallbackQuery, _Call(**kwargs)),
        invalid_data="bad",
        valid_data="__process_info__:17",
        target_user_id=17,
        invalid_text_contains="Invalid process info request format",
        denied_text="denied",
        missing_message_text_contains="Cannot render process info",
    )

    monkeypatch.setattr(
        top_process_module,
        "psutil_adapter",
        cast(
            object,
            type("_P", (), {"get_top_processes": staticmethod(lambda count=10: [])})(),
        ),
    )
    handler(cast(CallbackQuery, _Call(data="__process_info__:17")), cast(TeleBot, bot))
    assert (
        "can't get process information" in str(bot.edited_messages[-1]["text"]).lower()
    )

    monkeypatch.setattr(
        top_process_module,
        "psutil_adapter",
        cast(
            object,
            type(
                "_P2",
                (),
                {
                    "get_top_processes": staticmethod(
                        lambda count=10: [
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
                        ]
                    )
                },
            )(),
        ),
    )
    monkeypatch.setattr(
        top_process_module.Compiler,
        "quick_render",
        lambda template_name, context, **emojis: context["process_table"],
    )
    monkeypatch.setattr(top_process_module, "running_in_docker", True)
    handler(cast(CallbackQuery, _Call(data="__process_info__:17")), cast(TeleBot, bot))
    rendered_table = cast(str, bot.edited_messages[-1]["text"])
    assert "PID" in rendered_table
    assert "Process Name" in rendered_table
    assert bot.edited_messages[-1]["parse_mode"] == "HTML"

    monkeypatch.setattr(
        top_process_module,
        "psutil_adapter",
        cast(
            object,
            type(
                "_P3",
                (),
                {
                    "get_top_processes": staticmethod(
                        lambda count=10: (_ for _ in ()).throw(RuntimeError("boom"))
                    )
                },
            )(),
        ),
    )
    with pytest.raises(exceptions.HandlingException) as exc_info:
        handler(
            cast(CallbackQuery, _Call(data="__process_info__:17")), cast(TeleBot, bot)
        )
    assert exc_info.value.context.error_code == "HAND_010"
