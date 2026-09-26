from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import cast

import pytest
from telebot import TeleBot
from telebot.types import Message

import pytmbot.handlers.bot_handlers.fallback as fallback_module


def _message(chat_type: str, text: str | None = "hello") -> Message:
    return cast(
        Message, SimpleNamespace(chat=SimpleNamespace(id=5, type=chat_type), text=text)
    )


@pytest.mark.parametrize(
    ("chat_type", "text", "expected"),
    [
        ("private", "hello", True),
        ("private", "/unknown", True),
        ("private", None, False),
        ("group", "hello", False),
        ("supergroup", "hello", False),
    ],
)
def test_fallback_only_answers_private_text(
    chat_type: str, text: str | None, expected: bool
) -> None:
    assert (
        fallback_module.is_unrecognized_private_text(_message(chat_type, text))
        is expected
    )


def test_fallback_replies_with_hint_and_main_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[tuple[int, str]] = []
    monkeypatch.setattr(
        fallback_module,
        "send_main_message",
        lambda bot, chat_id, text: sent.append((chat_id, text)),
    )
    handler = cast(
        Callable[[Message, TeleBot], None],
        getattr(
            fallback_module.handle_unrecognized_message,
            "__wrapped__",
            fallback_module.handle_unrecognized_message,
        ),
    )

    handler(_message("private"), cast(TeleBot, object()))

    assert len(sent) == 1
    assert sent[0][0] == 5
    assert "/help" in sent[0][1]
