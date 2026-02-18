from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, cast

import pytest
from telebot import TeleBot
from telebot.types import CallbackQuery

CallbackBuilder = Callable[..., CallbackQuery]
CallbackHandler = Callable[[CallbackQuery, TeleBot], object]


class _CallbackAnswerBot(Protocol):
    callback_answers: list[dict[str, object]]


def assert_standard_callback_auth_paths(
    *,
    monkeypatch: pytest.MonkeyPatch,
    module: object,
    handler: CallbackHandler,
    bot: _CallbackAnswerBot,
    call_builder: CallbackBuilder,
    invalid_data: str,
    valid_data: str,
    target_user_id: int,
    invalid_text_contains: str,
    denied_text: str,
    missing_message_text_contains: str,
) -> None:
    """Assert parse/auth/missing-message branches shared by many callback handlers."""

    def _raise_invalid_parse(data: str | None, prefix: str) -> int:
        del data, prefix
        raise ValueError("bad")

    monkeypatch.setattr(module, "parse_callback_target_user", _raise_invalid_parse)
    handler(call_builder(data=invalid_data), cast(TeleBot, bot))
    callback_text = str(bot.callback_answers[-1]["text"])
    assert invalid_text_contains in callback_text

    monkeypatch.setattr(
        module,
        "parse_callback_target_user",
        lambda data, prefix: target_user_id,
    )
    monkeypatch.setattr(
        module,
        "authorize_callback_request",
        lambda call, target_user_id, require_owner_match: (False, denied_text),
    )
    handler(call_builder(data=valid_data), cast(TeleBot, bot))
    denied_callback_text = str(bot.callback_answers[-1]["text"])
    assert denied_callback_text == denied_text

    monkeypatch.setattr(
        module,
        "authorize_callback_request",
        lambda call, target_user_id, require_owner_match: (True, ""),
    )
    handler(call_builder(data=valid_data, message=None), cast(TeleBot, bot))
    missing_message_callback_text = str(bot.callback_answers[-1]["text"])
    assert missing_message_text_contains in missing_message_callback_text
