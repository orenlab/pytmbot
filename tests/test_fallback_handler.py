from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import cast

import pytest
from telebot import TeleBot
from telebot.types import Message

import pytmbot.handlers.bot_handlers.fallback as fallback_module

ALLOWED_USER_ID = 123456789  # listed in pytmbot.yaml.sample
UNKNOWN_USER_ID = 42


def _message(
    chat_type: str, text: str | None = "hello", user_id: int = ALLOWED_USER_ID
) -> Message:
    return cast(
        Message,
        SimpleNamespace(
            chat=SimpleNamespace(id=5, type=chat_type),
            from_user=SimpleNamespace(id=user_id),
            text=text,
        ),
    )


def _unwrapped_handler() -> Callable[[Message, TeleBot], None]:
    return cast(
        Callable[[Message, TeleBot], None],
        getattr(
            fallback_module.handle_unrecognized_message,
            "__wrapped__",
            fallback_module.handle_unrecognized_message,
        ),
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


def test_fallback_ignores_users_outside_allowlist() -> None:
    message = _message("private", "/GETMYID", user_id=UNKNOWN_USER_ID)

    assert fallback_module.is_unrecognized_private_text(message) is False


def test_fallback_replies_with_hint_and_main_menu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[tuple[int, str]] = []
    monkeypatch.setattr(
        fallback_module,
        "send_main_message",
        lambda bot, chat_id, text: sent.append((chat_id, text)),
    )

    _unwrapped_handler()(_message("private"), cast(TeleBot, object()))

    assert len(sent) == 1
    assert sent[0][0] == 5
    assert "/help" in sent[0][1]


@pytest.mark.parametrize(
    ("auth_state", "text", "expects_totp_hint"),
    [
        ("processing", "12345", True),
        ("processing", "123 456", True),
        ("processing", "hello", False),
        ("unauthenticated", "12345", False),
    ],
)
def test_fallback_routes_near_miss_codes_during_2fa(
    monkeypatch: pytest.MonkeyPatch,
    auth_state: str,
    text: str,
    expects_totp_hint: bool,
) -> None:
    state_fabric = fallback_module.session_manager.state_fabric
    state = (
        state_fabric.PROCESSING
        if auth_state == "processing"
        else state_fabric.UNAUTHENTICATED
    )
    monkeypatch.setattr(
        fallback_module,
        "session_manager",
        SimpleNamespace(
            state_fabric=state_fabric, get_auth_state=lambda user_id: state
        ),
    )
    verified: list[str | None] = []
    sent: list[str] = []
    monkeypatch.setattr(
        fallback_module,
        "handle_totp_code_verification",
        lambda message, bot: verified.append(message.text),
    )
    monkeypatch.setattr(
        fallback_module,
        "send_main_message",
        lambda bot, chat_id, text: sent.append(text),
    )

    _unwrapped_handler()(_message("private", text), cast(TeleBot, object()))

    assert verified == ([text] if expects_totp_hint else [])
    assert len(sent) == (0 if expects_totp_hint else 1)
