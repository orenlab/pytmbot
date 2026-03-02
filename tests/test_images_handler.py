from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import cast

import pytest
from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, Message

import pytmbot.handlers.docker_handlers.images as images_module
from pytmbot import exceptions
from pytmbot.parsers.compiler import Compiler

type _PayloadValue = (
    str | int | float | bool | None | dict[str, _PayloadValue] | list[_PayloadValue]
)
type _PayloadDict = dict[str, _PayloadValue]
type _MessageHandler = Callable[[Message, TeleBot], bool]
type _RawHandlerInput = (
    Callable[..., bool] | Callable[[Callable[..., bool]], Callable[..., bool]]
)
type _InlineButtons = list[dict[str, str]]


@dataclass
class _User:
    id: int = 7


@dataclass
class _Chat:
    id: int = 11


@dataclass
class _Message:
    chat: _Chat = field(default_factory=_Chat)
    from_user: _User | None = field(default_factory=_User)


@dataclass
class _Bot:
    actions: list[tuple[int, str]] = field(default_factory=list)
    sent_messages: list[_PayloadDict] = field(default_factory=list)

    def send_chat_action(self, chat_id: int, action: str) -> bool:
        self.actions.append((chat_id, action))
        return True

    def send_message(self, chat_id: int, text: str, **kwargs: _PayloadValue) -> str:
        payload: _PayloadDict = {"chat_id": chat_id, "text": text, **kwargs}
        self.sent_messages.append(payload)
        return "sent"


def _raw_handler(handler: _RawHandlerInput) -> _MessageHandler:
    wrapped = handler
    for _ in range(2):
        wrapped = getattr(wrapped, "__wrapped__", wrapped)
    return cast(_MessageHandler, wrapped)


def _keyboard_callbacks(keyboard: _InlineButtons) -> list[str]:
    return [item["callback_data"] for item in keyboard]


def _assert_rendered_text_and_get_callbacks(
    rendered: tuple[str, InlineKeyboardMarkup | _InlineButtons] | None,
    *,
    expected_text: str,
) -> list[str]:
    assert rendered is not None
    text, keyboard = rendered
    assert text == expected_text
    if isinstance(keyboard, InlineKeyboardMarkup):
        return [
            str(button.callback_data)
            for row in keyboard.keyboard
            for button in row
            if button.callback_data is not None
        ]
    return _keyboard_callbacks(keyboard)


def test_truncate_helpers() -> None:
    assert images_module._truncate_text(None, max_length=5) == "N/A"
    assert images_module._truncate_text("abcdef", max_length=4) == "a..."

    assert images_module._truncate_list("bad") == []
    long_list = ["x" * 20] * 7
    truncated = images_module._truncate_list(long_list, max_items=2, max_item_length=6)
    assert len(truncated) == 3
    assert truncated[-1] == "... +5 more"

    assert images_module._truncate_labels("bad") == {}
    labels = {f"k{i}": "v" * 100 for i in range(8)}
    normalized = images_module._truncate_labels(labels)
    assert "__truncated__" in normalized


def test_compact_and_prepare_images_for_listing() -> None:
    image = {
        "id": "sha256:" + "a" * 200,
        "name": "repo/image:tag",
        "tags": ["t1", "t2", "t3", "t4", "t5", "t6", "t7"],
        "repo_digests": ["repo/image@sha256:abc", "repo/image@sha256:def"],
        "layers_count": 6,
        "healthcheck": "test=CMD curl",
        "labels": {"k": "v"},
        "cmd": ["python", "main.py"],
    }
    compact = images_module._compact_image_for_listing(image)
    assert compact["name"] == "repo/image:tag"
    assert isinstance(compact["tags"], list)
    assert compact["tags"][-1] == "... +1 more"
    assert compact["layers_count"] == 6
    assert compact["repo_digests_count"] == 2

    prepared = images_module._prepare_images_for_listing([image])
    assert len(prepared) == 1
    assert prepared[0]["name"] == "repo/image:tag"


def test_load_images_data_cache_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(images_module, "_images_cache", None)

    timestamps = iter([100.0, 101.0, 200.0])
    monkeypatch.setattr(
        "pytmbot.handlers.docker_handlers.images.time.time",
        lambda: next(timestamps),
    )

    calls = {"count": 0}

    def _fetch() -> list[_PayloadDict | str]:
        calls["count"] += 1
        return [{"name": "img"}, "bad"]

    monkeypatch.setattr(images_module, "fetch_image_details", _fetch)

    first = images_module._load_images_data()
    second = images_module._load_images_data()
    third = images_module._load_images_data()

    assert calls["count"] == 2
    assert first == [{"name": "img"}]
    assert second == [{"name": "img"}]
    assert third == [{"name": "img"}]

    monkeypatch.setattr(images_module, "_images_cache", None)
    monkeypatch.setattr(
        "pytmbot.handlers.docker_handlers.images.time.time",
        lambda: 1000.0,
    )
    monkeypatch.setattr(images_module, "fetch_image_details", lambda: None)

    with pytest.raises(exceptions.DockerOperationException) as exc_info:
        images_module._load_images_data()
    assert exc_info.value.context.error_code == "DOCKER_003"


def test_render_paginated_images_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(images_module, "MAX_TELEGRAM_MESSAGE_LENGTH", 25)
    monkeypatch.setattr(
        images_module,
        "_render_images_page_text",
        lambda page_items, page, total_pages, total_items: "X" * 500,
    )
    monkeypatch.setattr(
        images_module,
        "em",
        type(
            "_Em",
            (),
            {
                "get_emoji": staticmethod(
                    lambda key: {"warning": "⚠️", "thought_balloon": "💭"}[key]
                )
            },
        )(),
    )

    text, page, total_pages, page_items, start_index = (
        images_module._render_paginated_images_text(
            [{"id": 1}, {"id": 2}],
            page=1,
        )
    )
    assert "Images view is too large" in text
    assert page == 1
    assert total_pages == 1
    assert page_items == []
    assert start_index == 0


def test_build_keyboard_render_page_and_handle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        images_module,
        "button_data",
        lambda text, callback_data: {"text": text, "callback_data": callback_data},
    )
    monkeypatch.setattr(
        images_module,
        "keyboards",
        type(
            "_Kbd",
            (),
            {"build_inline_keyboard": staticmethod(lambda buttons: buttons)},
        )(),
    )
    monkeypatch.setattr(
        images_module,
        "em",
        type(
            "_Em",
            (),
            {
                "get_emoji": staticmethod(
                    lambda key: {
                        "BACK_arrow": "⬅️",
                        "next_track_button": "⏭️",
                        "package": "📦",
                    }[key]
                )
            },
        )(),
    )

    keyboard = images_module._build_images_keyboard(
        page=2,
        total_pages=3,
        user_id=7,
        page_items=[{"name": "repo/app:1.0"}],
        start_index=4,
    )
    callbacks = [item["callback_data"] for item in cast(_InlineButtons, keyboard)]
    assert "__image_info__:4:7:2" in callbacks
    assert "__images_page__:1:7" in callbacks
    assert "__images_page__:3:7" in callbacks
    assert "__check_updates__:7" in callbacks

    keyboard_single = images_module._build_images_keyboard(
        page=1,
        total_pages=1,
        user_id=7,
        page_items=[],
        start_index=0,
    )
    callbacks_single = [
        item["callback_data"] for item in cast(_InlineButtons, keyboard_single)
    ]
    assert callbacks_single == ["__check_updates__:7"]

    monkeypatch.setattr(images_module, "_load_images_data", lambda: [{"name": "img"}])
    monkeypatch.setattr(
        images_module, "_prepare_images_for_listing", lambda images: [{"name": "img"}]
    )
    monkeypatch.setattr(
        images_module,
        "_render_paginated_images_text",
        lambda images, page: ("images-page", 1, 1, [{"name": "img"}], 0),
    )
    monkeypatch.setattr(
        images_module,
        "_build_images_keyboard",
        lambda page, total_pages, user_id, page_items, start_index: "kbd",
    )

    rendered_text, rendered_keyboard = images_module.render_images_page(
        page=1, user_id=7
    )
    assert rendered_text == "images-page"
    assert cast(str, rendered_keyboard) == "kbd"

    sent_payloads: list[_PayloadDict] = []
    monkeypatch.setattr(
        images_module, "render_images_page", lambda page, user_id: ("images-ui", "kbd")
    )

    def _send(
        bot: TeleBot,
        chat_id: int,
        text: str,
        reply_markup: _PayloadValue,
        parse_mode: str,
    ) -> bool:
        del bot
        sent_payloads.append(
            {
                "chat_id": chat_id,
                "text": text,
                "reply_markup": reply_markup,
                "parse_mode": parse_mode,
            }
        )
        return True

    monkeypatch.setattr(images_module, "send_telegram_message", _send)

    bot = _Bot()
    handler = _raw_handler(images_module.handle_images)
    result = handler(cast(Message, _Message()), cast(TeleBot, bot))
    assert result is True
    assert sent_payloads[-1]["text"] == "images-ui"
    assert bot.actions[-1] == (11, "typing")

    monkeypatch.setattr(
        images_module,
        "render_images_page",
        lambda page, user_id: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    with pytest.raises(exceptions.HandlingException) as exc_info:
        handler(cast(Message, _Message()), cast(TeleBot, bot))
    assert exc_info.value.context.error_code == "HAND_010"
    assert (
        "error occurred while processing the command"
        in str(bot.sent_messages[-1]["text"]).lower()
    )


def test_image_info_callback_helpers_and_details_render(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    callback_data = images_module.build_image_info_callback_data(
        image_index=4,
        user_id=11,
        page=2,
    )
    assert callback_data == "__image_info__:4:11:2"
    assert images_module.parse_image_info_callback_data(callback_data) == (4, 11, 2)
    assert images_module.parse_image_info_callback_data("bad") is None
    extra_callback = images_module.build_image_extra_callback_data(
        action="history",
        image_index=4,
        user_id=11,
        page=2,
    )
    assert extra_callback == "__image_extra__:history:4:11:2"
    assert images_module.parse_image_extra_callback_data(extra_callback) == (
        "history",
        4,
        11,
        2,
    )
    assert (
        images_module.parse_image_extra_callback_data("__image_extra__:bad:4:11:2")
        is None
    )

    monkeypatch.setattr(
        images_module,
        "_load_images_data",
        lambda: [
            {
                "id": "sha256:abc",
                "name": "repo/app:1.0",
                "tags": ["repo/app:1.0"],
                "repo_digests": ["repo/app@sha256:abc"],
                "architecture": "amd64",
                "variant": "N/A",
                "os": "linux",
                "size": "1 MiB",
                "virtual_size": "1 MiB",
                "shared_size": "N/A",
                "created": "a minute ago",
                "created_at": "2026-02-19 00:00:00 UTC",
                "author": "dev",
                "docker_version": "29.2.0",
                "comment": "N/A",
                "parent_id": "N/A",
                "rootfs_type": "layers",
                "layers_count": 1,
                "labels": {"com.example": "1"},
                "label_count": 1,
                "exposed_ports": ["8080/tcp"],
                "env_variables": ["A=1"],
                "entrypoint": ["python"],
                "cmd": ["main.py"],
                "shell": ["/bin/sh", "-c"],
                "volumes": ["/data"],
                "user": "root",
                "working_dir": "/app",
                "stop_signal": "SIGTERM",
                "healthcheck": "none",
            }
        ],
    )
    monkeypatch.setattr(
        Compiler,
        "quick_render",
        lambda template_name, context: template_name,
    )
    monkeypatch.setattr(
        images_module,
        "button_data",
        lambda text, callback_data: {"text": text, "callback_data": callback_data},
    )
    monkeypatch.setattr(
        images_module,
        "keyboards",
        type(
            "_Kbd",
            (),
            {"build_inline_keyboard": staticmethod(lambda buttons: buttons)},
        )(),
    )
    monkeypatch.setattr(
        images_module,
        "em",
        type("_Em", (), {"get_emoji": staticmethod(lambda key: "⬅️")})(),
    )

    rendered = images_module.render_image_details(image_index=0, page=2, user_id=11)
    details_callbacks = _assert_rendered_text_and_get_callbacks(
        rendered,
        expected_text="d_image_full_info.jinja2",
    )
    assert "__image_extra__:history:0:11:2" in details_callbacks
    assert "__image_extra__:usage:0:11:2" in details_callbacks
    assert "__images_page__:2:11" in details_callbacks

    assert (
        images_module.render_image_details(image_index=99, page=2, user_id=11) is None
    )

    monkeypatch.setattr(
        images_module,
        "get_image_history",
        lambda image_id: [
            {
                "id": "sha256:layer1",
                "created": "now",
                "created_by": "RUN apk add curl",
                "size": "1 KiB",
                "comment": "",
            }
        ],
    )
    monkeypatch.setattr(
        images_module,
        "get_image_usage",
        lambda image_id: {
            "containers": [
                {
                    "name": "pytmbot",
                    "id": "abc123",
                    "status": "running",
                    "started_at": "2026-02-19 15:00:00 UTC",
                }
            ],
            "containers_count": 1,
            "running_count": 1,
            "stopped_count": 0,
        },
    )

    history_rendered = images_module.render_image_extra_info(
        action="history",
        image_index=0,
        page=2,
        user_id=11,
    )
    history_callbacks = _assert_rendered_text_and_get_callbacks(
        history_rendered,
        expected_text="d_image_history_info.jinja2",
    )
    assert "__image_info__:0:11:2" in history_callbacks
    assert "__images_page__:2:11" in history_callbacks

    usage_rendered = images_module.render_image_extra_info(
        action="usage",
        image_index=0,
        page=2,
        user_id=11,
    )
    assert usage_rendered is not None
    usage_text, _usage_keyboard = usage_rendered
    assert usage_text == "d_image_usage_info.jinja2"


def test_image_details_template_line_breaks_and_env_pre() -> None:
    image_context: dict[str, object] = {
        "name": "repo/app:1.0",
        "id": "sha256:abc",
        "tags_count": 1,
        "tags": ["repo/app:1.0"],
        "repo_digests_count": 1,
        "repo_digests": ["repo/app@sha256:abc"],
        "parent_id": "N/A",
        "os": "linux",
        "architecture": "amd64",
        "variant": "N/A",
        "size": "1 MiB",
        "virtual_size": "1 MiB",
        "shared_size": "N/A",
        "layers_count": 1,
        "rootfs_type": "layers",
        "created": "now",
        "created_at": "2026-02-19 15:00:00 UTC",
        "user": "root",
        "working_dir": "/app",
        "stop_signal": "SIGTERM",
        "entrypoint": ["python"],
        "cmd": ["main.py"],
        "shell": [],
        "healthcheck": "none",
        "exposed_ports_count": 1,
        "exposed_ports": ["8080/tcp"],
        "volumes_count": 0,
        "volumes": [],
        "env_variables_count": 2,
        "env_variables": ["A=1", "B=2"],
        "author": "N/A",
        "docker_version": "N/A",
        "comment": "N/A",
        "label_count": 1,
        "labels": {"k": "v"},
    }
    rendered = Compiler.quick_render(
        "d_image_full_info.jinja2",
        context={
            "image": image_context,
            "emojis": {
                "thought_balloon": "💭",
                "package": "📦",
                "spouting_whale": "🐳",
                "bookmark_tabs": "📑",
                "gear": "⚙️",
                "key": "🔑",
                "electric_plug": "🔌",
                "label": "🏷️",
                "minus": "➖",
            },
        },
    )

    assert "Tags:</code> repo/app:1.0\n<code>Repo digests:" in rendered
    assert "<code>Env vars (2):</code>\n<pre>A=1\nB=2\n</pre>" in rendered
