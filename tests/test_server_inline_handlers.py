from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from types import ModuleType
from typing import cast

import pytest
from telebot import TeleBot
from telebot.types import CallbackQuery

import pytmbot.handlers.server_handlers.health_summary as health_module
import pytmbot.handlers.server_handlers.inline.common as inline_common_module
import pytmbot.handlers.server_handlers.inline.swap as swap_module
import pytmbot.handlers.server_handlers.inline.system_views as system_views_module
import pytmbot.handlers.server_handlers.inline.top_process as top_process_module
from pytmbot import exceptions
from pytmbot.parsers.compiler import Compiler
from tests._inline_edit_helpers import assert_reply_markup_has_callbacks
from tests._telebot_objects import (
    record_callback_answer,
    record_edited_message,
    unwrap_handler,
)

_NOT_MODIFIED_DESCRIPTION = (
    "Bad Request: message is not modified: specified new message content and reply "
    "markup are exactly the same as a current content and reply markup of the message"
)

type _PayloadValue = (
    str | int | float | bool | None | dict[str, _PayloadValue] | list[_PayloadValue]
)
type _PayloadDict = dict[str, _PayloadValue]
type _CallbackHandler = Callable[[CallbackQuery, TeleBot], None]
type _RawHandlerInput = (
    Callable[..., _CallbackHandler | None]
    | Callable[..., None]
    | Callable[[Callable[..., None]], Callable[..., None]]
)


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
        record_callback_answer(self.callback_answers, callback_query_id, **kwargs)
        return True

    def edit_message_text(self, **kwargs: _PayloadValue) -> str:
        record_edited_message(self.edited_messages, **kwargs)
        return "edited"


def _raw_handler(handler: _RawHandlerInput) -> _CallbackHandler:
    return cast(_CallbackHandler, unwrap_handler(handler, depth=2))


def _invoke(
    handler: _CallbackHandler,
    bot: _Bot,
    *,
    data: str,
) -> None:
    handler(cast(CallbackQuery, _Call(data=data)), cast(TeleBot, bot))


def _patch_auth_with_answer(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    *,
    text: str,
    result: tuple[bool, int | None],
) -> None:
    def _fake_auth(
        call: CallbackQuery, bot: TeleBot, **_kwargs: _PayloadValue
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
    monkeypatch: pytest.MonkeyPatch, module: ModuleType, target_user_id: int = 17
) -> None:
    monkeypatch.setattr(
        module,
        "authorize_user_bound_callback",
        lambda call, bot, **kwargs: (True, target_user_id),
    )


def _assert_common_auth_paths(
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    handler: _CallbackHandler,
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
    module: ModuleType,
    handler_obj: _RawHandlerInput,
    invalid_data: str,
    valid_data: str,
    invalid_text: str,
    denied_text: str,
    missing_text_fragment: str,
) -> tuple[_Bot, _CallbackHandler]:
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
    module: ModuleType,
    *,
    method_name: str,
    implementation: Callable[
        ..., None | dict[str, float | str | int] | list[dict[str, float | str | int]]
    ],
) -> None:
    monkeypatch.setattr(
        module,
        "psutil_adapter",
        type("_Adapter", (), {method_name: staticmethod(implementation)})(),
    )


def _install_api_exception_stub(
    monkeypatch: pytest.MonkeyPatch, module: ModuleType
) -> type[Exception]:
    class _ApiTelegramExceptionStub(Exception):
        def __init__(self, description: str, error_code: int = 400) -> None:
            super().__init__(description)
            self.description = description
            self.error_code = error_code

    monkeypatch.setattr(module, "ApiTelegramException", _ApiTelegramExceptionStub)
    return _ApiTelegramExceptionStub


def _assert_not_modified_callback_answer(
    monkeypatch: pytest.MonkeyPatch,
    bot: _Bot,
    *,
    invoke: Callable[[], None],
    expected_text: str,
) -> None:
    api_exception_stub = _install_api_exception_stub(monkeypatch, inline_common_module)

    def _raise_not_modified(**_kwargs: _PayloadValue) -> str:
        raise api_exception_stub(_NOT_MODIFIED_DESCRIPTION)

    bot.edit_message_text = _raise_not_modified  # type: ignore[method-assign]
    invoke()
    assert bot.callback_answers[-1]["text"] == expected_text


def test_handle_swap_info_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    bot, handler = _prepare_handler_with_auth_paths(
        monkeypatch,
        module=swap_module,
        handler_obj=swap_module.handle_swap_info,
        invalid_data="bad",
        valid_data="__swap_info__:17",
        invalid_text="This button is no longer valid. Please open Memory again.",
        denied_text="denied",
        missing_text_fragment="This message can no longer be updated. Please open Memory again.",
    )
    _patch_auth_success(monkeypatch, swap_module)
    _patch_adapter_method(
        monkeypatch,
        swap_module,
        method_name="get_swap_memory",
        implementation=lambda: None,
    )
    _invoke(handler, bot, data="__swap_info__:17")
    assert (
        "couldn't retrieve swap information"
        in str(bot.edited_messages[-1]["text"]).lower()
    )
    assert_reply_markup_has_callbacks(
        bot.edited_messages[-1].get("reply_markup"),
        expected_callbacks=["__swap_info__:17"],
    )

    _patch_adapter_method(
        monkeypatch,
        swap_module,
        method_name="get_swap_memory",
        implementation=lambda: {"used": "1 GiB"},
    )
    monkeypatch.setattr(Compiler, "quick_render", lambda **kwargs: "swap-ok")
    _invoke(handler, bot, data="__swap_info__:17")
    assert bot.edited_messages[-1]["text"] == "swap-ok"
    assert_reply_markup_has_callbacks(
        bot.edited_messages[-1].get("reply_markup"),
        expected_callbacks=["__swap_info__:17"],
    )

    _patch_adapter_method(
        monkeypatch,
        swap_module,
        method_name="get_swap_memory",
        implementation=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(exceptions.HandlingException) as exc_info:
        _invoke(handler, bot, data="__swap_info__:17")
    assert exc_info.value.context.error_code == "HAND_009"
    error_markup = bot.edited_messages[-1].get("reply_markup")
    assert error_markup is not None


def test_handle_process_info_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    bot, handler = _prepare_handler_with_auth_paths(
        monkeypatch,
        module=top_process_module,
        handler_obj=top_process_module.handle_process_info,
        invalid_data="bad",
        valid_data="__process_info__:17",
        invalid_text="This button is no longer valid. Please open Process again.",
        denied_text="denied",
        missing_text_fragment="This message can no longer be updated. Please open Process again.",
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
        "couldn't retrieve process information"
        in str(bot.edited_messages[-1]["text"]).lower()
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
        Compiler,
        "quick_render",
        lambda template_name, context, **emojis: context["process_table"],
    )
    monkeypatch.setattr(top_process_module, "running_in_docker", True)
    _invoke(handler, bot, data="__process_info__:17")
    rendered_table = cast(str, bot.edited_messages[-1]["text"])
    assert "PID" in rendered_table
    assert "Process Name" in rendered_table
    assert bot.edited_messages[-1]["parse_mode"] == "HTML"
    assert_reply_markup_has_callbacks(
        bot.edited_messages[-1].get("reply_markup"),
        expected_callbacks=["__cpu_info__:17", "__process_info__:17"],
    )

    _invoke(handler, bot, data="__process_info_process__:17")
    process_origin_markup = bot.edited_messages[-1].get("reply_markup")
    assert_reply_markup_has_callbacks(
        process_origin_markup,
        expected_callbacks=["__process_overview__:17", "__process_info_process__:17"],
    )
    assert process_origin_markup is not None
    process_origin_callbacks = [
        getattr(button, "callback_data", "")
        for row in getattr(process_origin_markup, "keyboard", [])
        for button in row
    ]
    assert "__cpu_info__:17" not in process_origin_callbacks

    _patch_adapter_method(
        monkeypatch,
        top_process_module,
        method_name="get_top_processes",
        implementation=lambda count=10: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(exceptions.HandlingException) as exc_info:
        _invoke(handler, bot, data="__process_info__:17")
    assert exc_info.value.context.error_code == "HAND_010"


def test_handle_system_health_refresh_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    bot, handler = _prepare_handler_with_auth_paths(
        monkeypatch,
        module=health_module,
        handler_obj=health_module.handle_system_health_refresh,
        invalid_data="bad",
        valid_data="__health_refresh__:17",
        invalid_text="This refresh button is no longer valid. Run /health again.",
        denied_text="denied",
        missing_text_fragment="This health message can no longer be refreshed. Run /health again.",
    )
    _patch_auth_success(monkeypatch, health_module)
    monkeypatch.setattr(
        health_module,
        "_render_health_message",
        lambda: "health-refresh-ok",
    )
    monkeypatch.setattr(
        health_module,
        "_build_health_keyboard",
        lambda user_id: {"inline": user_id},
    )

    _invoke(handler, bot, data="__health_refresh__:17")
    assert bot.edited_messages[-1]["text"] == "health-refresh-ok"
    assert bot.callback_answers[-1]["text"] == "Health snapshot updated."

    monkeypatch.setattr(
        health_module,
        "_render_health_message",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(exceptions.HandlingException) as exc_info:
        _invoke(handler, bot, data="__health_refresh__:17")
    assert exc_info.value.context.error_code == "HAND_HEALTH_002"


def test_handle_system_health_refresh_ignores_not_modified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot, handler = _prepare_handler_with_auth_paths(
        monkeypatch,
        module=health_module,
        handler_obj=health_module.handle_system_health_refresh,
        invalid_data="bad",
        valid_data="__health_refresh__:17",
        invalid_text="This refresh button is no longer valid. Run /health again.",
        denied_text="denied",
        missing_text_fragment="This health message can no longer be refreshed. Run /health again.",
    )
    _patch_auth_success(monkeypatch, health_module)
    monkeypatch.setattr(
        health_module,
        "_render_health_message",
        lambda: "health-refresh-ok",
    )
    monkeypatch.setattr(
        health_module,
        "_build_health_keyboard",
        lambda user_id: {"inline": user_id},
    )

    _assert_not_modified_callback_answer(
        monkeypatch,
        bot,
        invoke=lambda: _invoke(handler, bot, data="__health_refresh__:17"),
        expected_text="Health snapshot is already current.",
    )


def test_system_views_edit_message_ignores_not_modified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _Bot()
    call = cast(CallbackQuery, _Call())
    _assert_not_modified_callback_answer(
        monkeypatch,
        bot,
        invoke=lambda: system_views_module._edit_message(
            call,
            cast(TeleBot, bot),
            text="same",
            parse_mode="HTML",
            reply_markup=None,
        ),
        expected_text="Already up to date.",
    )


def test_system_views_edit_message_handles_rate_limited_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _Bot()
    call = cast(CallbackQuery, _Call())

    api_exception_stub = _install_api_exception_stub(monkeypatch, inline_common_module)

    def _raise_rate_limited(**_kwargs: _PayloadValue) -> str:
        raise api_exception_stub("Too Many Requests: retry after 9", 429)

    bot.edit_message_text = _raise_rate_limited  # type: ignore[method-assign]
    was_edited = inline_common_module.edit_callback_message_text(
        call,
        cast(TeleBot, bot),
        text="same",
        parse_mode="HTML",
        reply_markup=None,
    )
    assert was_edited is False
    assert (
        bot.callback_answers[-1]["text"]
        == "Telegram API is rate limited. Try again in 9s."
    )


def test_system_views_edit_message_reraises_other_telegram_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _Bot()
    call = cast(CallbackQuery, _Call())

    api_exception_stub = _install_api_exception_stub(monkeypatch, inline_common_module)

    def _raise_chat_not_found(**_kwargs: _PayloadValue) -> str:
        raise api_exception_stub("chat not found", 400)

    bot.edit_message_text = _raise_chat_not_found  # type: ignore[method-assign]
    with pytest.raises(api_exception_stub):
        system_views_module._edit_message(
            call,
            cast(TeleBot, bot),
            text="will-fail",
            parse_mode="HTML",
            reply_markup=None,
        )


def test_handle_swap_info_ignores_not_modified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _Bot()
    handler = _raw_handler(swap_module.handle_swap_info)
    _patch_auth_success(monkeypatch, swap_module)
    _patch_adapter_method(
        monkeypatch,
        swap_module,
        method_name="get_swap_memory",
        implementation=lambda: None,
    )

    _assert_not_modified_callback_answer(
        monkeypatch,
        bot,
        invoke=lambda: _invoke(handler, bot, data="__swap_info__:17"),
        expected_text="Already up to date.",
    )


def test_handle_process_info_ignores_not_modified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _Bot()
    handler = _raw_handler(top_process_module.handle_process_info)
    _patch_auth_success(monkeypatch, top_process_module)
    _patch_adapter_method(
        monkeypatch,
        top_process_module,
        method_name="get_top_processes",
        implementation=lambda count=10: [],
    )

    _assert_not_modified_callback_answer(
        monkeypatch,
        bot,
        invoke=lambda: _invoke(handler, bot, data="__process_info__:17"),
        expected_text="Already up to date.",
    )


def test_handle_process_overview_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    bot, handler = _prepare_handler_with_auth_paths(
        monkeypatch,
        module=top_process_module,
        handler_obj=top_process_module.handle_process_overview,
        invalid_data="bad",
        valid_data="__process_overview__:17",
        invalid_text="This button is no longer valid. Please open Process again.",
        denied_text="denied",
        missing_text_fragment="This message can no longer be updated. Please open Process again.",
    )
    _patch_auth_success(monkeypatch, top_process_module)
    monkeypatch.setattr(
        top_process_module, "render_process_overview_text", lambda: None
    )
    _invoke(handler, bot, data="__process_overview__:17")
    assert (
        "couldn't retrieve process information"
        in str(bot.edited_messages[-1]["text"]).lower()
    )
    assert_reply_markup_has_callbacks(
        bot.edited_messages[-1].get("reply_markup"),
        expected_callbacks=["__process_info_process__:17"],
    )

    monkeypatch.setattr(
        top_process_module, "render_process_overview_text", lambda: "process-overview"
    )
    _invoke(handler, bot, data="__process_overview__:17")
    assert bot.edited_messages[-1]["text"] == "process-overview"
    assert bot.edited_messages[-1]["parse_mode"] == "HTML"
    assert_reply_markup_has_callbacks(
        bot.edited_messages[-1].get("reply_markup"),
        expected_callbacks=["__process_info_process__:17"],
    )

    monkeypatch.setattr(
        top_process_module,
        "render_process_overview_text",
        lambda: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(exceptions.HandlingException) as exc_info:
        _invoke(handler, bot, data="__process_overview__:17")
    assert exc_info.value.context.error_code == "HAND_011"
