from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, cast

import pytest
from telebot import TeleBot
from telebot.types import CallbackQuery

import pytmbot.handlers.docker_handlers.inline.container_info as container_info_module
import pytmbot.handlers.docker_handlers.inline.manage as manage_module


@dataclass
class _User:
    id: int = 11


@dataclass
class _Chat:
    id: int = 22


@dataclass
class _Message:
    chat: _Chat = field(default_factory=_Chat)
    message_id: int = 33


@dataclass
class _Call:
    id: str = "cb"
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


def _raw_handler(handler: object) -> Callable[..., object]:
    wrapped = handler
    for _ in range(3):
        wrapped = getattr(wrapped, "__wrapped__", wrapped)
    return cast(Callable[..., object], wrapped)


def _prepare_handler_context(
    monkeypatch: pytest.MonkeyPatch,
    *,
    module: object,
    handler_obj: object,
) -> tuple[Callable[..., object], _Bot, list[str]]:
    handler = _raw_handler(handler_obj)
    bot = _Bot()
    shown: list[str] = []
    monkeypatch.setattr(
        module,
        "show_handler_info",
        lambda call, text, bot=None: shown.append(text),
    )
    return handler, bot, shown


def test_validate_container_name() -> None:
    assert container_info_module.validate_container_name("api-1") is True
    assert container_info_module.validate_container_name("") is False
    assert container_info_module.validate_container_name("../etc") is False
    assert container_info_module.validate_container_name("bad|name") is False


def test_handle_container_full_info_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    handler, bot, shown = _prepare_handler_context(
        monkeypatch,
        module=container_info_module,
        handler_obj=container_info_module.handle_containers_full_info,
    )

    handler(cast(CallbackQuery, _Call(data=None)), cast(TeleBot, bot))
    assert shown[-1] == "Invalid request format"

    monkeypatch.setattr(
        container_info_module,
        "parse_container_full_info_callback_data",
        lambda data: None,
    )
    handler(cast(CallbackQuery, _Call(data="bad")), cast(TeleBot, bot))
    assert shown[-1] == "Invalid request format"

    monkeypatch.setattr(
        container_info_module,
        "parse_container_full_info_callback_data",
        lambda data: ("api", 11, 2),
    )
    monkeypatch.setattr(
        container_info_module,
        "authorize_docker_callback_request",
        lambda **kwargs: (False, "denied"),
    )
    handler(cast(CallbackQuery, _Call(data="ok")), cast(TeleBot, bot))
    assert shown[-1] == "Container info: denied"

    monkeypatch.setattr(
        container_info_module,
        "authorize_docker_callback_request",
        lambda **kwargs: (True, ""),
    )
    monkeypatch.setattr(
        container_info_module, "validate_container_name", lambda name: False
    )
    handler(cast(CallbackQuery, _Call(data="ok")), cast(TeleBot, bot))
    assert shown[-1] == "Invalid container name format"

    monkeypatch.setattr(
        container_info_module, "validate_container_name", lambda name: True
    )
    monkeypatch.setattr(
        container_info_module, "get_comprehensive_container_details", lambda name: {}
    )
    handler(cast(CallbackQuery, _Call(data="ok")), cast(TeleBot, bot))
    assert shown[-1] == "api: Container not found"

    class _Access:
        allowed_admins_ids = [11]

    class _Settings:
        access_control = _Access()

    monkeypatch.setattr(container_info_module, "settings", _Settings())
    monkeypatch.setattr(
        container_info_module,
        "get_comprehensive_container_details",
        lambda name: {"name": "api", "state": "running"},
    )
    monkeypatch.setattr(
        container_info_module,
        "get_emojis",
        lambda: {
            "spiral_calendar": "📅",
            "bullseye": "🎯",
            "BACK_arrow": "⬅️",
            "thought_balloon": "💭",
            "package": "📦",
            "gear": "⚙️",
            "chart_increasing": "📈",
            "globe_with_meridians": "🌐",
            "herb": "🌿",
            "banjo": "🪕",
        },
    )
    monkeypatch.setattr(
        container_info_module.Compiler,
        "quick_render",
        lambda **kwargs: "container-full",
    )
    monkeypatch.setattr(
        container_info_module,
        "button_data",
        lambda text, callback_data: {"text": text, "callback_data": callback_data},
    )
    monkeypatch.setattr(
        container_info_module,
        "keyboards",
        cast(
            object,
            type(
                "_Kbd",
                (),
                {"build_inline_keyboard": staticmethod(lambda buttons: buttons)},
            )(),
        ),
    )

    handler(cast(CallbackQuery, _Call(data="ok")), cast(TeleBot, bot))
    callbacks = cast(list[dict[str, str]], bot.edited_messages[-1]["reply_markup"])
    callback_data = [item["callback_data"] for item in callbacks]
    assert bot.edited_messages[-1]["text"] == "container-full"
    assert any(value.startswith("__get_logs__") for value in callback_data)
    assert any(value.startswith("__manage__") for value in callback_data)
    assert any(value.startswith("__containers_page__") for value in callback_data)

    handler(cast(CallbackQuery, _Call(data="ok", message=None)), cast(TeleBot, bot))
    assert shown[-1] == "Cannot render container details in this context"

    monkeypatch.setattr(
        container_info_module,
        "parse_container_full_info_callback_data",
        lambda data: (_ for _ in ()).throw(ValueError("bad")),
    )
    handler(cast(CallbackQuery, _Call(data="bad")), cast(TeleBot, bot))
    assert shown[-1] == "Invalid request data"

    monkeypatch.setattr(
        container_info_module,
        "parse_container_full_info_callback_data",
        lambda data: ("api", 11, 1),
    )
    monkeypatch.setattr(
        container_info_module, "validate_container_name", lambda name: True
    )
    monkeypatch.setattr(
        container_info_module,
        "get_comprehensive_container_details",
        lambda name: {"name": "api"},
    )
    monkeypatch.setattr(
        container_info_module.Compiler,
        "quick_render",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("render fail")),
    )
    handler(cast(CallbackQuery, _Call(data="ok")), cast(TeleBot, bot))
    assert shown[-1] == "An error occurred while processing request"


def test_handle_manage_container_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    handler, bot, shown = _prepare_handler_context(
        monkeypatch,
        module=manage_module,
        handler_obj=manage_module.handle_manage_container,
    )

    monkeypatch.setattr(
        manage_module,
        "get_authorized_container_callback_context",
        lambda **kwargs: None,
    )
    handler(cast(CallbackQuery, _Call(data="__manage__:api:11")), cast(TeleBot, bot))

    @dataclass
    class _AuthContext:
        container_name: str
        user_id: int

    monkeypatch.setattr(
        manage_module,
        "get_authorized_container_callback_context",
        lambda **kwargs: _AuthContext(container_name="api", user_id=11),
    )

    class _DockerContext:
        def __enter__(self) -> str:
            return "adapter"

        def __exit__(
            self,
            exc_type: object,
            exc: object,
            tb: object,
        ) -> Literal[False]:
            return False

    monkeypatch.setattr(
        manage_module, "docker_client_context", lambda: _DockerContext()
    )
    monkeypatch.setattr(
        manage_module,
        "button_data",
        lambda text, callback_data: {"text": text, "callback_data": callback_data},
    )
    monkeypatch.setattr(
        manage_module,
        "keyboards",
        cast(
            object,
            type(
                "_Kbd",
                (),
                {"build_inline_keyboard": staticmethod(lambda buttons: buttons)},
            )(),
        ),
    )
    monkeypatch.setattr(
        manage_module,
        "em",
        cast(object, type("_Em", (), {"get_emoji": staticmethod(lambda key: key)})()),
    )
    monkeypatch.setattr(
        manage_module.Compiler, "quick_render", lambda *args, **kwargs: "manage-ui"
    )

    monkeypatch.setattr(
        manage_module,
        "get_container_state",
        lambda container_name, docker_client: "running",
    )
    handler(cast(CallbackQuery, _Call(data="__manage__:api:11")), cast(TeleBot, bot))
    running_callbacks = cast(
        list[dict[str, str]], bot.edited_messages[-1]["reply_markup"]
    )
    running_values = [item["callback_data"] for item in running_callbacks]
    assert any(value.startswith("__stop__") for value in running_values)
    assert any(value.startswith("__restart__") for value in running_values)

    monkeypatch.setattr(
        manage_module,
        "get_container_state",
        lambda container_name, docker_client: "exited",
    )
    handler(cast(CallbackQuery, _Call(data="__manage__:api:11")), cast(TeleBot, bot))
    stopped_callbacks = cast(
        list[dict[str, str]], bot.edited_messages[-1]["reply_markup"]
    )
    stopped_values = [item["callback_data"] for item in stopped_callbacks]
    assert any(value.startswith("__start__") for value in stopped_values)

    handler(
        cast(CallbackQuery, _Call(data="__manage__:api:11", message=None)),
        cast(TeleBot, bot),
    )
    assert shown[-1] == "Managing api: Missing callback message"
