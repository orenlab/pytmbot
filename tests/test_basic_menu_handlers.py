from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import cast

import pytest
from telebot import TeleBot
from telebot.types import Message

import pytmbot.handlers.bot_handlers.about as about_module
import pytmbot.handlers.bot_handlers.navigation as navigation_module
import pytmbot.handlers.bot_handlers.start as start_module
import pytmbot.handlers.docker_handlers.containers as containers_module
import pytmbot.handlers.docker_handlers.docker as docker_module
import pytmbot.handlers.server_handlers.server as server_module
from pytmbot import exceptions


@dataclass
class _User:
    id: int = 1
    first_name: str | None = "Denis"
    username: str | None = "den_user"


@dataclass
class _Chat:
    id: int = 10


@dataclass
class _Message:
    chat: _Chat = field(default_factory=_Chat)
    from_user: _User | None = field(default_factory=_User)
    message_id: int = 101


@dataclass
class _Bot:
    actions: list[tuple[int, str]] = field(default_factory=list)
    sent_messages: list[dict[str, object]] = field(default_factory=list)

    def send_chat_action(self, chat_id: int, action: str) -> bool:
        self.actions.append((chat_id, action))
        return True

    def send_message(self, chat_id: int, text: str, **kwargs: object) -> str:
        self.sent_messages.append({"chat_id": chat_id, "text": text, **kwargs})
        return "sent"


def _raw_handler(handler: object) -> Callable[[Message, TeleBot], None]:
    raw = getattr(handler, "__wrapped__", handler)
    return cast(Callable[[Message, TeleBot], None], raw)


def test_about_handler_success_and_error(monkeypatch: pytest.MonkeyPatch) -> None:
    sent_payloads: list[dict[str, object]] = []
    monkeypatch.setattr(
        about_module.Compiler,
        "quick_render",
        lambda template_name, context: "about-text",
    )
    monkeypatch.setattr(
        about_module,
        "send_telegram_message",
        lambda **kwargs: sent_payloads.append(kwargs),
    )

    bot = _Bot()
    handler = _raw_handler(about_module.handle_about_command)
    handler(cast(Message, _Message()), cast(TeleBot, bot))
    assert sent_payloads and sent_payloads[0]["text"] == "about-text"
    assert bot.actions == [(10, "typing")]

    monkeypatch.setattr(
        about_module.Compiler,
        "quick_render",
        lambda template_name, context: (_ for _ in ()).throw(RuntimeError("template fail")),
    )
    with pytest.raises(exceptions.HandlingException) as exc_info:
        handler(cast(Message, _Message()), cast(TeleBot, bot))
    assert exc_info.value.context.error_code == "HAND_018"


def test_navigation_start_and_server_handlers(monkeypatch: pytest.MonkeyPatch) -> None:
    sent_payloads: list[dict[str, object]] = []
    monkeypatch.setattr(
        navigation_module,
        "send_telegram_message",
        lambda **kwargs: sent_payloads.append(kwargs),
    )
    monkeypatch.setattr(
        start_module,
        "send_telegram_message",
        lambda **kwargs: sent_payloads.append(kwargs),
    )
    monkeypatch.setattr(
        navigation_module.Compiler,
        "quick_render",
        lambda template_name, first_name, **kwargs: (
            f"nav:{first_name}"
            if template_name == "b_back.jinja2"
            else (
                f"start:{first_name}"
                if template_name == "b_index.jinja2"
                else f"server:{first_name}"
            )
        ),
    )

    monkeypatch.setattr(
        navigation_module,
        "keyboards",
        cast(object, type("_Kbd", (), {"build_reply_keyboard": staticmethod(lambda keyboard_type=None: "nav-kbd")})()),
    )
    monkeypatch.setattr(
        start_module,
        "keyboards",
        cast(object, type("_Kbd2", (), {"build_reply_keyboard": staticmethod(lambda keyboard_type=None: "start-kbd")})()),
    )
    monkeypatch.setattr(
        server_module,
        "keyboards",
        cast(
            object,
            type(
                "_Kbd3",
                (),
                {"build_reply_keyboard": staticmethod(lambda keyboard_type=None: "server-kbd")},
            )(),
        ),
    )
    monkeypatch.setattr(navigation_module, "em", cast(object, type("_Em", (), {"get_emoji": staticmethod(lambda _name: "e")})()))
    monkeypatch.setattr(server_module, "em", cast(object, type("_Em2", (), {"get_emoji": staticmethod(lambda _name: "e")})()))

    bot = _Bot()
    navigation_handler = _raw_handler(navigation_module.handle_navigation)
    start_handler = _raw_handler(start_module.handle_start)
    server_handler = _raw_handler(server_module.handle_server)

    navigation_handler(cast(Message, _Message()), cast(TeleBot, bot))
    start_handler(cast(Message, _Message()), cast(TeleBot, bot))
    server_handler(cast(Message, _Message()), cast(TeleBot, bot))
    assert len(sent_payloads) >= 2
    assert any(str(payload["text"]).startswith("nav:") for payload in sent_payloads)
    assert any(str(payload["text"]).startswith("start:") for payload in sent_payloads)
    assert any(str(msg["text"]).startswith("server:") for msg in bot.sent_messages)

    monkeypatch.setattr(
        server_module.Compiler,
        "quick_render",
        lambda template_name, first_name, **kwargs: (_ for _ in ()).throw(RuntimeError("server fail")),
    )
    with pytest.raises(exceptions.HandlingException) as exc_info:
        server_handler(cast(Message, _Message()), cast(TeleBot, bot))
    assert exc_info.value.context.error_code == "HAND_002"


def test_docker_fetch_compile_and_handle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        docker_module,
        "fetch_docker_counters",
        lambda: {"images_count": 2, "containers_count": 1, "bad": "x"},
    )
    counters = docker_module.__fetch_counters()
    assert counters == {"images_count": 2, "containers_count": 1}

    monkeypatch.setattr(
        docker_module.Compiler,
        "quick_render",
        lambda template_name, context, **kwargs: "docker-rendered",
    )
    assert docker_module.__compile_message() == "docker-rendered"

    monkeypatch.setattr(
        docker_module,
        "fetch_docker_counters",
        lambda: "invalid",
    )
    with pytest.raises(ValueError):
        docker_module.__fetch_counters()

    monkeypatch.setattr(
        docker_module,
        "fetch_docker_counters",
        lambda: {"images_count": 2},
    )
    monkeypatch.setattr(
        docker_module.Compiler,
        "quick_render",
        lambda template_name, context, **kwargs: (_ for _ in ()).throw(RuntimeError("template")),
    )
    with pytest.raises(exceptions.TemplateError):
        docker_module.__compile_message()

    sent_payloads: list[dict[str, object]] = []
    monkeypatch.setattr(
        docker_module,
        "send_telegram_message",
        lambda **kwargs: sent_payloads.append(kwargs),
    )
    monkeypatch.setattr(
        docker_module,
        "__compile_message",
        lambda: "docker-ui",
    )
    monkeypatch.setattr(
        docker_module,
        "keyboards",
        cast(object, type("_Kbd", (), {"build_reply_keyboard": staticmethod(lambda keyboard_type=None: "docker-kbd")})()),
    )

    bot = _Bot()
    handler = _raw_handler(docker_module.handle_docker)
    handler(cast(Message, _Message()), cast(TeleBot, bot))
    assert sent_payloads and sent_payloads[0]["text"] == "docker-ui"

    monkeypatch.setattr(
        docker_module,
        "__compile_message",
        lambda: (_ for _ in ()).throw(RuntimeError("docker fail")),
    )
    with pytest.raises(exceptions.HandlingException) as exc_info:
        handler(cast(Message, _Message()), cast(TeleBot, bot))
    assert exc_info.value.context.error_code == "HAND_011"


def test_containers_render_and_handler_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        containers_module,
        "retrieve_containers_stats",
        lambda: [{"name": "app", "id": "abc"}],
    )
    assert containers_module._get_container_data() == [{"name": "app", "id": "abc"}]

    monkeypatch.setattr(
        containers_module,
        "retrieve_containers_stats",
        lambda: "invalid",
    )
    assert containers_module._get_container_data() == []

    monkeypatch.setattr(
        containers_module,
        "retrieve_containers_stats",
        lambda: (_ for _ in ()).throw(RuntimeError("fetch failed")),
    )
    with pytest.raises(exceptions.DockerOperationException):
        containers_module._get_container_data()

    monkeypatch.setattr(
        containers_module.Compiler,
        "quick_render",
        lambda template_name, context, **kwargs: "containers-empty",
    )
    assert containers_module._render_empty_message() == "containers-empty"

    monkeypatch.setattr(
        containers_module,
        "_get_container_data",
        lambda: [],
    )
    text, keyboard = containers_module.render_containers_page(page=1, user_id=1)
    assert text == "containers-empty"
    assert keyboard is None

    monkeypatch.setattr(
        containers_module,
        "_get_container_data",
        lambda: [{"name": "app", "id": "abc"}],
    )
    monkeypatch.setattr(
        containers_module,
        "_render_paginated_container_text",
        lambda container_data, page, initial_page_size=containers_module.CONTAINERS_DEFAULT_PAGE_SIZE: (
            "page-text",
            [{"name": "app", "id": "abc"}],
            1,
            1,
        ),
    )
    real_build_keyboard = containers_module._build_containers_keyboard

    monkeypatch.setattr(
        containers_module,
        "_build_containers_keyboard",
        lambda page_items, page, total_pages, user_id: "kbd",
    )
    text2, keyboard2 = containers_module.render_containers_page(page=1, user_id=7)
    assert text2 == "page-text"
    assert keyboard2 == "kbd"
    monkeypatch.setattr(
        containers_module,
        "_build_containers_keyboard",
        real_build_keyboard,
    )

    monkeypatch.setattr(
        containers_module,
        "button_data",
        lambda text, callback_data: {"text": text, "callback_data": callback_data},
    )
    monkeypatch.setattr(
        containers_module,
        "keyboards",
        cast(object, type("_Kbd2", (), {"build_inline_keyboard": staticmethod(lambda buttons: buttons)})()),
    )
    monkeypatch.setattr(
        containers_module,
        "em",
        cast(
            object,
            type(
                "_Em",
                (),
                {"get_emoji": staticmethod(lambda key: {"BACK_arrow": "⬅️", "next_track_button": "⏭️", "warning": "⚠️"}[key])},
            )(),
        ),
    )
    keyboard_buttons = containers_module._build_containers_keyboard(
        [{"name": "app", "id": "abc"}],
        page=2,
        total_pages=3,
        user_id=5,
    )
    assert isinstance(keyboard_buttons, list)
    callbacks = [
        str(item["callback_data"])
        for item in keyboard_buttons
        if isinstance(item, dict) and "callback_data" in item
    ]
    assert any(str(callback).startswith("__get_full__") for callback in callbacks)

    sent_payloads: list[dict[str, object]] = []
    monkeypatch.setattr(
        containers_module,
        "send_telegram_message",
        lambda **kwargs: sent_payloads.append(kwargs),
    )
    monkeypatch.setattr(
        containers_module,
        "render_containers_page",
        lambda page, user_id: ("containers-ui", "kbd"),
    )

    bot = _Bot()
    handler = _raw_handler(containers_module.handle_containers)
    handler(cast(Message, _Message(from_user=_User(id=55))), cast(TeleBot, bot))
    assert sent_payloads and sent_payloads[0]["text"] == "containers-ui"

    monkeypatch.setattr(
        containers_module,
        "render_containers_page",
        lambda page, user_id: (_ for _ in ()).throw(RuntimeError("containers fail")),
    )
    with pytest.raises(exceptions.HandlingException) as exc_info:
        handler(cast(Message, _Message()), cast(TeleBot, bot))
    assert exc_info.value.context.error_code == "HAND_012"
