from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest
from telebot import TeleBot
from telebot.apihelper import ApiTelegramException

from pytmbot.middleware.callback_ack import CallbackAcknowledger


class _QueryTooOld(ApiTelegramException):
    def __init__(self) -> None:
        Exception.__init__(self, "Bad Request: query is too old")
        self.error_code = 400


class _BotStub:
    def __init__(self, *, fail: bool = False) -> None:
        self.answers: list[dict[str, object]] = []
        self.fail = fail

    def answer_callback_query(self, *args: object, **kwargs: object) -> bool:
        if self.fail:
            raise _QueryTooOld()
        payload = dict(kwargs)
        if args:
            payload["callback_query_id"] = args[0]
        self.answers.append(payload)
        return True


def _middleware(bot: _BotStub) -> CallbackAcknowledger:
    return CallbackAcknowledger(cast(TeleBot, bot))


def test_acknowledges_callback_left_unanswered_by_handler() -> None:
    bot = _BotStub()
    middleware = _middleware(bot)

    middleware.post_process(SimpleNamespace(id="cb-1"), {}, None)

    assert bot.answers == [{"callback_query_id": "cb-1", "text": None}]


def test_skips_callbacks_already_answered_by_handler() -> None:
    bot = _BotStub()
    middleware = _middleware(bot)

    # Handlers call the (now tracked) bot method, positionally or by keyword.
    cast(TeleBot, bot).answer_callback_query("cb-1", text="Done")  # type: ignore[arg-type]
    bot.answer_callback_query(callback_query_id="cb-2", text="Done", show_alert=True)
    middleware.post_process(SimpleNamespace(id="cb-1"), {}, None)
    middleware.post_process(SimpleNamespace(id="cb-2"), {}, None)

    assert [answer["callback_query_id"] for answer in bot.answers] == ["cb-1", "cb-2"]


def test_reports_handler_errors_as_a_toast() -> None:
    bot = _BotStub()
    middleware = _middleware(bot)

    middleware.post_process(SimpleNamespace(id="cb-3"), {}, RuntimeError("boom"))

    assert bot.answers == [
        {"callback_query_id": "cb-3", "text": CallbackAcknowledger.ERROR_TEXT},
    ]


def test_ignores_expired_callback_queries() -> None:
    bot = _BotStub(fail=True)
    middleware = _middleware(bot)

    middleware.post_process(SimpleNamespace(id="cb-5"), {}, None)
    middleware.pre_process(SimpleNamespace(id="cb-5"), {})


def test_tracking_is_bounded() -> None:
    bot = _BotStub()
    middleware = CallbackAcknowledger(cast(TeleBot, bot), max_tracked=2)

    for index in range(3):
        bot.answer_callback_query(callback_query_id=f"cb-{index}")
    middleware.post_process(SimpleNamespace(id="cb-0"), {}, None)

    assert bot.answers[-1] == {"callback_query_id": "cb-0", "text": None}
    with pytest.raises(ValueError):
        CallbackAcknowledger(cast(TeleBot, bot), max_tracked=0)
