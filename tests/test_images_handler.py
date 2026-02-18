from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import cast

import pytest
from telebot import TeleBot
from telebot.types import Message

import pytmbot.handlers.docker_handlers.images as images_module
from pytmbot import exceptions


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
    sent_messages: list[dict[str, object]] = field(default_factory=list)

    def send_chat_action(self, chat_id: int, action: str) -> bool:
        self.actions.append((chat_id, action))
        return True

    def send_message(self, chat_id: int, text: str, **kwargs: object) -> str:
        payload: dict[str, object] = {"chat_id": chat_id, "text": text, **kwargs}
        self.sent_messages.append(payload)
        return "sent"


def _raw_handler(handler: object) -> Callable[[Message, TeleBot], bool]:
    wrapped = handler
    for _ in range(2):
        wrapped = getattr(wrapped, "__wrapped__", wrapped)
    return cast(Callable[[Message, TeleBot], bool], wrapped)


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
        "labels": {"k": "v"},
        "cmd": ["python", "main.py"],
    }
    compact = images_module._compact_image_for_listing(image)
    assert compact["name"] == "repo/image:tag"
    assert isinstance(compact["tags"], list)
    assert compact["tags"][-1] == "... +1 more"

    prepared = images_module._prepare_images_for_listing([image])
    assert len(prepared) == 1
    assert prepared[0]["name"] == "repo/image:tag"


def test_load_images_data_cache_and_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(images_module, "_images_cache", None)

    timestamps = iter([100.0, 101.0, 200.0])
    monkeypatch.setattr(images_module.time, "time", lambda: next(timestamps))

    calls = {"count": 0}

    def _fetch() -> list[object]:
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
    monkeypatch.setattr(images_module.time, "time", lambda: 1000.0)
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
        cast(
            object,
            type(
                "_Em",
                (),
                {
                    "get_emoji": staticmethod(
                        lambda key: {"warning": "⚠️", "thought_balloon": "💭"}[key]
                    )
                },
            )(),
        ),
    )

    text, page, total_pages = images_module._render_paginated_images_text(
        [{"id": 1}, {"id": 2}],
        page=1,
    )
    assert "Images view is too large" in text
    assert page == 1
    assert total_pages == 1


def test_build_keyboard_render_page_and_handle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        images_module,
        "button_data",
        lambda text, callback_data: {"text": text, "callback_data": callback_data},
    )
    monkeypatch.setattr(
        images_module,
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
        images_module,
        "em",
        cast(
            object,
            type(
                "_Em",
                (),
                {
                    "get_emoji": staticmethod(
                        lambda key: {
                            "BACK_arrow": "⬅️",
                            "next_track_button": "⏭️",
                        }[key]
                    )
                },
            )(),
        ),
    )

    keyboard = images_module._build_images_keyboard(page=2, total_pages=3, user_id=7)
    callbacks = [
        cast(str, item["callback_data"])
        for item in cast(list[dict[str, object]], keyboard)
    ]
    assert "__images_page__:1:7" in callbacks
    assert "__images_page__:3:7" in callbacks
    assert "__check_updates__:7" in callbacks

    keyboard_single = images_module._build_images_keyboard(
        page=1, total_pages=1, user_id=7
    )
    callbacks_single = [
        cast(str, item["callback_data"])
        for item in cast(list[dict[str, object]], keyboard_single)
    ]
    assert callbacks_single == ["__check_updates__:7"]

    monkeypatch.setattr(images_module, "_load_images_data", lambda: [{"name": "img"}])
    monkeypatch.setattr(
        images_module, "_prepare_images_for_listing", lambda images: [{"name": "img"}]
    )
    monkeypatch.setattr(
        images_module,
        "_render_paginated_images_text",
        lambda images, page: ("images-page", 1, 1),
    )
    monkeypatch.setattr(
        images_module,
        "_build_images_keyboard",
        lambda page, total_pages, user_id: "kbd",
    )

    rendered_text, rendered_keyboard = images_module.render_images_page(
        page=1, user_id=7
    )
    assert rendered_text == "images-page"
    assert rendered_keyboard == "kbd"

    sent_payloads: list[dict[str, object]] = []
    monkeypatch.setattr(
        images_module, "render_images_page", lambda page, user_id: ("images-ui", "kbd")
    )

    def _send(
        bot: object,
        chat_id: int,
        text: str,
        reply_markup: object,
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
