from __future__ import annotations

from collections import OrderedDict
from types import SimpleNamespace
from typing import Any, cast

import pytest
import requests
from telebot import TeleBot
from telebot.apihelper import ApiTelegramException
from telebot.types import InlineKeyboardMarkup, ReplyKeyboardMarkup

from pytmbot.handlers.handlers_util import utils as utils_module
from pytmbot.keyboards.keyboards import NAV_DOCKER, NAV_MAIN, NAV_SERVER


class _BotStub:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def send_message(self, **kwargs: Any) -> dict[str, Any]:
        payload = dict(kwargs)
        self.messages.append(payload)
        return {"message_id": len(self.messages), **payload}


def test_truncate_telegram_text_leaves_short_messages_unchanged() -> None:
    text = "hello"
    assert utils_module.truncate_telegram_text(text) == text


def test_truncate_telegram_text_truncates_long_messages() -> None:
    text = "x" * 5000
    truncated = utils_module.truncate_telegram_text(text)
    assert len(truncated) < len(text)
    assert "4096 characters" in truncated


def test_send_bot_message_prefers_explicit_reply_markup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inline = cast(InlineKeyboardMarkup, object())

    def _resolve(
        reply_markup: object | None,
        *,
        nav_keyboard: str | None = None,
    ) -> object | None:
        del nav_keyboard
        return reply_markup

    monkeypatch.setattr(utils_module, "resolve_reply_markup", _resolve)
    bot = _BotStub()
    utils_module.send_bot_message(
        bot,  # type: ignore[arg-type]
        1,
        "ok",
        reply_markup=inline,
    )
    assert bot.messages[0]["reply_markup"] is inline
    assert len(bot.messages) == 1


def test_send_bot_message_syncs_nav_keyboard_after_inline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inline = InlineKeyboardMarkup()
    nav = cast(ReplyKeyboardMarkup, object())

    monkeypatch.setattr(utils_module, "build_nav_keyboard", lambda _name: nav)
    bot = _BotStub()
    utils_module.send_bot_message(
        bot,  # type: ignore[arg-type]
        7,
        "overview",
        reply_markup=inline,
        nav_keyboard=NAV_MAIN,
    )
    assert len(bot.messages) == 2
    assert bot.messages[0]["reply_markup"] is inline
    assert bot.messages[0]["text"] == "overview"
    assert bot.messages[1]["reply_markup"] is nav
    assert bot.messages[1]["text"] == utils_module.NAV_KEYBOARD_SYNC_TEXT
    assert bot.messages[1]["disable_notification"] is True


def test_send_main_server_and_docker_messages_attach_nav_keyboards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str | None] = []

    def _send_bot_message(
        _bot: object,
        _chat_id: int,
        _text: str,
        *,
        nav_keyboard: str | None = None,
        **kwargs: object,
    ) -> dict[str, str]:
        del kwargs
        captured.append(nav_keyboard)
        return {"message_id": "1"}

    monkeypatch.setattr(utils_module, "send_bot_message", _send_bot_message)
    bot = cast(TeleBot, object())
    utils_module.send_main_message(bot, 1, "main")
    utils_module.send_server_message(bot, 1, "server")
    utils_module.send_docker_message(bot, 1, "docker")
    assert captured == [NAV_MAIN, NAV_SERVER, NAV_DOCKER]


def test_send_telegram_message_uses_keyword_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def _send_bot_message(
        _bot: object,
        chat_id: int,
        text: str,
        **kwargs: object,
    ) -> dict[str, object]:
        captured["chat_id"] = chat_id
        captured["text"] = text
        captured.update(kwargs)
        return {"message_id": 1}

    monkeypatch.setattr(utils_module, "send_bot_message", _send_bot_message)
    assert (
        utils_module.send_telegram_message(
            object(),  # type: ignore[arg-type]
            42,
            "payload",
            parse_mode="Markdown",
            nav_keyboard=NAV_MAIN,
        )
        is True
    )
    assert captured["chat_id"] == 42
    assert captured["text"] == "payload"
    assert captured["parse_mode"] == "Markdown"
    assert captured["nav_keyboard"] == NAV_MAIN


def test_build_referer_main_keyboard_is_persistent_and_not_one_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import pytmbot.keyboards.keyboards as keyboards_module
    from pytmbot.settings import KeyboardSettings

    keyboards_module.Keyboards._get_keyboard_data.cache_clear()
    monkeypatch.setattr(keyboards_module, "keyboard_settings", KeyboardSettings())
    markup = keyboards_module.Keyboards().build_referer_main_keyboard("Server")
    assert isinstance(markup, ReplyKeyboardMarkup)
    assert markup.is_persistent is True
    assert markup.one_time_keyboard is False


class _MessageGone(ApiTelegramException):
    def __init__(self) -> None:
        Exception.__init__(self, "Bad Request: message to delete not found")
        self.error_code = 400


def test_nav_keyboard_sync_keeps_only_latest_follow_up(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nav = cast(ReplyKeyboardMarkup, object())
    monkeypatch.setattr(utils_module, "build_nav_keyboard", lambda _name: nav)
    monkeypatch.setattr(utils_module, "_nav_sync_messages", OrderedDict())

    class _Bot:
        def __init__(self) -> None:
            self.next_id = 100
            self.deleted: list[tuple[int, int]] = []

        def send_message(self, **kwargs: object) -> SimpleNamespace:
            self.next_id += 1
            return SimpleNamespace(message_id=self.next_id, **kwargs)

        def delete_message(self, chat_id: int, message_id: int) -> bool:
            self.deleted.append((chat_id, message_id))
            if message_id == 102:
                raise _MessageGone()
            return True

    bot = _Bot()
    for _ in range(3):
        utils_module.send_nav_keyboard_sync(cast(TeleBot, bot), 7, "server_keyboard")
    utils_module.send_nav_keyboard_sync(cast(TeleBot, bot), 8, "docker_keyboard")

    # Each new follow-up removes the previous one in the same chat only;
    # a failed deletion (already gone) is ignored.
    assert bot.deleted == [(7, 101), (7, 102)]
    assert dict(utils_module._nav_sync_messages) == {7: 103, 8: 104}


def test_nav_keyboard_sync_keeps_newest_when_handlers_finish_out_of_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nav = cast(ReplyKeyboardMarkup, object())
    monkeypatch.setattr(utils_module, "build_nav_keyboard", lambda _name: nav)
    monkeypatch.setattr(utils_module, "_nav_sync_messages", OrderedDict({7: 11}))
    deleted: list[int] = []
    bot = SimpleNamespace(
        send_message=lambda **kwargs: SimpleNamespace(message_id=10),
        delete_message=lambda chat_id, message_id: deleted.append(message_id),
    )

    utils_module.send_nav_keyboard_sync(cast(TeleBot, bot), 7, "server_keyboard")

    assert deleted == [10]
    assert dict(utils_module._nav_sync_messages) == {7: 11}


class _TooManyRequests(ApiTelegramException):
    def __init__(self) -> None:
        Exception.__init__(self, "Too Many Requests: retry after 3")
        self.error_code = 429


@pytest.mark.parametrize(
    "error",
    [_TooManyRequests(), requests.ConnectionError("connection reset")],
)
def test_nav_keyboard_sync_failure_does_not_raise(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    nav = cast(ReplyKeyboardMarkup, object())
    monkeypatch.setattr(utils_module, "build_nav_keyboard", lambda _name: nav)
    monkeypatch.setattr(utils_module, "_nav_sync_messages", OrderedDict({7: 11}))

    def _fail(**kwargs: object) -> None:
        raise error

    bot = SimpleNamespace(send_message=_fail)

    utils_module.send_nav_keyboard_sync(cast(TeleBot, bot), 7, "server_keyboard")

    assert dict(utils_module._nav_sync_messages) == {7: 11}
