from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import cast

import pytest
from telebot import TeleBot
from telebot.handler_backends import CancelUpdate
from telebot.types import CallbackQuery, Message

import pytmbot.middleware.update_dedup as update_dedup_module

type _PayloadScalar = str | int | float | bool | None
type _PayloadValue = _PayloadScalar | list["_PayloadValue"] | dict[str, "_PayloadValue"]
type _PayloadDict = dict[str, _PayloadValue]


@dataclass(slots=True)
class _UpdateLike:
    update_id: int


def _build_message(*, chat_id: int, message_id: int | None) -> Message:
    payload: _PayloadDict = {
        "message_id": message_id,
        "date": 1,
        "chat": {"id": chat_id, "type": "private"},
        "from": {"id": 99, "is_bot": False, "first_name": "T"},
        "text": "x",
    }
    message_from_json = cast(Callable[[_PayloadDict], Message], Message.de_json)
    message = message_from_json(payload)
    if not isinstance(message, Message):
        raise AssertionError("Expected Message instance")
    return message


def _build_callback(*, callback_id: str, message_id: int = 1) -> CallbackQuery:
    payload: _PayloadDict = {
        "id": callback_id,
        "from": {"id": 99, "is_bot": False, "first_name": "T"},
        "chat_instance": "test-chat-instance",
        "data": "x",
        "message": {
            "message_id": message_id,
            "date": 1,
            "chat": {"id": 500, "type": "private"},
            "from": {"id": 99, "is_bot": False, "first_name": "T"},
            "text": "x",
        },
    }
    callback_from_json = cast(
        Callable[[_PayloadDict], CallbackQuery], CallbackQuery.de_json
    )
    callback = callback_from_json(payload)
    if not isinstance(callback, CallbackQuery):
        raise AssertionError("Expected CallbackQuery instance")
    return callback


def test_update_dedup_rejects_invalid_configuration() -> None:
    with pytest.raises(ValueError):
        update_dedup_module.UpdateDedup(
            cast(TeleBot, SimpleNamespace()),
            ttl_seconds=0,
            max_entries=16,
        )
    with pytest.raises(ValueError):
        update_dedup_module.UpdateDedup(
            cast(TeleBot, SimpleNamespace()),
            ttl_seconds=30,
            max_entries=0,
        )


def test_update_dedup_drops_duplicate_callback_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 10.0
    middleware = update_dedup_module.UpdateDedup(
        cast(TeleBot, SimpleNamespace()),
        ttl_seconds=60,
        max_entries=32,
    )
    monkeypatch.setattr(middleware, "_now", lambda: now)
    callback = _build_callback(callback_id="cb-1")

    first = middleware.pre_process(callback, {})
    second = middleware.pre_process(callback, {})
    stats = middleware.get_stats()

    assert first is None
    assert isinstance(second, CancelUpdate)
    assert stats["accepted_updates"] == 1
    assert stats["dropped_duplicates"] == 1
    assert stats["cache_size"] == 1


def test_update_dedup_uses_update_id_and_supports_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now_ref = {"value": 1.0}
    middleware = update_dedup_module.UpdateDedup(
        cast(TeleBot, SimpleNamespace()),
        ttl_seconds=5,
        max_entries=8,
    )
    monkeypatch.setattr(middleware, "_now", lambda: float(now_ref["value"]))
    update_zero = _UpdateLike(update_id=0)

    assert middleware.pre_process(update_zero, {}) is None
    assert isinstance(middleware.pre_process(update_zero, {}), CancelUpdate)

    now_ref["value"] = 7.0
    assert middleware.pre_process(update_zero, {}) is None


def test_update_dedup_falls_back_to_message_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    middleware = update_dedup_module.UpdateDedup(
        cast(TeleBot, SimpleNamespace()),
        ttl_seconds=60,
        max_entries=32,
    )
    monkeypatch.setattr(middleware, "_now", lambda: 20.0)
    same_message_first = _build_message(chat_id=10, message_id=5)
    same_message_second = _build_message(chat_id=10, message_id=5)
    different_message = _build_message(chat_id=10, message_id=6)

    assert middleware.pre_process(same_message_first, {}) is None
    assert isinstance(middleware.pre_process(same_message_second, {}), CancelUpdate)
    assert middleware.pre_process(different_message, {}) is None


def test_update_dedup_eviction_respects_max_entries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    middleware = update_dedup_module.UpdateDedup(
        cast(TeleBot, SimpleNamespace()),
        ttl_seconds=120,
        max_entries=2,
    )
    monkeypatch.setattr(middleware, "_now", lambda: 100.0)
    first = _UpdateLike(update_id=1)
    second = _UpdateLike(update_id=2)
    third = _UpdateLike(update_id=3)

    assert middleware.pre_process(first, {}) is None
    assert middleware.pre_process(second, {}) is None
    assert middleware.pre_process(third, {}) is None

    # First key should be evicted by capacity and become accepted again.
    assert middleware.pre_process(first, {}) is None

    # Third key should still be active after the eviction churn above.
    assert isinstance(middleware.pre_process(third, {}), CancelUpdate)
    assert middleware.get_stats()["cache_size"] == 2


def test_update_dedup_ignores_unknown_updates() -> None:
    middleware = update_dedup_module.UpdateDedup(
        cast(TeleBot, SimpleNamespace()),
        ttl_seconds=60,
        max_entries=4,
    )
    unknown_update = object()

    assert middleware.pre_process(unknown_update, {}) is None
    stats = middleware.get_stats()
    assert stats["accepted_updates"] == 0
    assert stats["dropped_duplicates"] == 0
    assert stats["cache_size"] == 0


def test_update_dedup_cleanup_clears_state(monkeypatch: pytest.MonkeyPatch) -> None:
    middleware = update_dedup_module.UpdateDedup(
        cast(TeleBot, SimpleNamespace()),
        ttl_seconds=60,
        max_entries=8,
    )
    monkeypatch.setattr(middleware, "_now", lambda: 55.0)

    assert middleware.pre_process(_build_callback(callback_id="cb-clean"), {}) is None
    assert middleware.get_stats()["cache_size"] == 1

    middleware.cleanup()
    cleaned_stats = middleware.get_stats()
    assert cleaned_stats["cache_size"] == 0
    assert cleaned_stats["queue_size"] == 0


def test_extract_callback_key_handles_empty_callback_id() -> None:
    callback = _build_callback(callback_id="")
    assert update_dedup_module.UpdateDedup._extract_callback_key(callback) is None


def test_extract_message_key_handles_missing_message_identifiers() -> None:
    message = _build_message(chat_id=77, message_id=None)
    assert update_dedup_module.UpdateDedup._extract_message_key(message) is None


def test_update_dedup_now_returns_monotonic_value() -> None:
    middleware = update_dedup_module.UpdateDedup(
        cast(TeleBot, SimpleNamespace()),
        ttl_seconds=60,
        max_entries=8,
    )
    assert middleware._now() >= 0.0


def test_update_dedup_post_process_handles_exceptions() -> None:
    middleware = update_dedup_module.UpdateDedup(
        cast(TeleBot, SimpleNamespace()),
        ttl_seconds=60,
        max_entries=8,
    )
    middleware.post_process(object(), {}, None)
    middleware.post_process(object(), {}, cast(Exception, CancelUpdate()))
    middleware.post_process(object(), {"k": "v"}, RuntimeError("boom"))
