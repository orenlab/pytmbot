from __future__ import annotations

from typing import Any, cast

import pytest
from telebot import TeleBot
from telebot.apihelper import ApiTelegramException
from telebot.types import InlineKeyboardMarkup, InputRichMessage, ReplyKeyboardMarkup

from pytmbot.handlers.handlers_util import rich_messages as rich_module
from pytmbot.handlers.handlers_util import utils as utils_module
from pytmbot.handlers.server_handlers.inline import common as inline_common_module
from pytmbot.keyboards.keyboards import NAV_DOCKER, NAV_MAIN, NAV_SERVER


class _RichBotStub:
    def __init__(self) -> None:
        self.rich_messages: list[dict[str, Any]] = []
        self.messages: list[dict[str, Any]] = []

    def send_rich_message(self, **kwargs: Any) -> dict[str, Any]:
        payload = dict(kwargs)
        self.rich_messages.append(payload)
        return {"message_id": len(self.rich_messages), **payload}

    def send_message(self, **kwargs: Any) -> dict[str, Any]:
        payload = dict(kwargs)
        self.messages.append(payload)
        return {"message_id": len(self.messages), **payload}


class _EditBotStub:
    def __init__(self) -> None:
        self.edits: list[dict[str, Any]] = []
        self.callback_answers: list[dict[str, Any]] = []

    def edit_message_text(self, **kwargs: Any) -> dict[str, Any]:
        payload = dict(kwargs)
        self.edits.append(payload)
        return payload

    def answer_callback_query(self, **kwargs: Any) -> None:
        self.callback_answers.append(dict(kwargs))


class _Chat:
    id = 11


class _Message:
    chat = _Chat()
    message_id = 22


class _Call:
    id = "cb-1"
    message = _Message()


def test_send_rich_bot_message_drops_classic_only_kwargs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _RichBotStub()
    rich_module.send_rich_bot_message(
        bot,  # type: ignore[arg-type]
        1,
        "<p>ok</p>",
        link_preview_options=object(),
        parse_mode="HTML",
        disable_notification=True,
    )
    assert len(bot.rich_messages) == 1
    assert "link_preview_options" not in bot.rich_messages[0]
    assert "parse_mode" not in bot.rich_messages[0]
    assert bot.rich_messages[0]["disable_notification"] is True


def test_build_rich_html_message_skips_entity_detection_by_default() -> None:
    rich = rich_module.build_rich_html_message("<h2>Metrics</h2>")
    assert isinstance(rich, InputRichMessage)
    assert rich.html == "<h2>Metrics</h2>"
    assert rich.skip_entity_detection is True


def test_build_rich_html_message_can_enable_entity_detection() -> None:
    rich = rich_module.build_rich_html_message(
        "<p>https://example.com</p>",
        skip_entity_detection=False,
    )
    assert rich.skip_entity_detection is False


def test_send_rich_bot_message_prefers_explicit_reply_markup(
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

    monkeypatch.setattr(rich_module, "resolve_reply_markup", _resolve)
    bot = _RichBotStub()
    rich_module.send_rich_bot_message(
        bot,  # type: ignore[arg-type]
        1,
        "<h2>ok</h2>",
        reply_markup=inline,
    )
    assert len(bot.rich_messages) == 1
    assert bot.rich_messages[0]["reply_markup"] is inline
    assert isinstance(bot.rich_messages[0]["rich_message"], InputRichMessage)
    assert bot.rich_messages[0]["rich_message"].html == "<h2>ok</h2>"
    assert len(bot.messages) == 0


def test_send_rich_bot_message_syncs_nav_keyboard_after_inline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inline = InlineKeyboardMarkup()
    nav = cast(ReplyKeyboardMarkup, object())

    monkeypatch.setattr(utils_module, "build_nav_keyboard", lambda _name: nav)
    bot = _RichBotStub()
    rich_module.send_rich_bot_message(
        bot,  # type: ignore[arg-type]
        7,
        "<h2>overview</h2>",
        reply_markup=inline,
        nav_keyboard=NAV_MAIN,
    )
    assert len(bot.rich_messages) == 1
    assert bot.rich_messages[0]["reply_markup"] is inline
    assert bot.rich_messages[0]["rich_message"].html == "<h2>overview</h2>"
    assert len(bot.messages) == 1
    assert bot.messages[0]["reply_markup"] is nav
    assert bot.messages[0]["text"] == utils_module.NAV_KEYBOARD_SYNC_TEXT
    assert bot.messages[0]["disable_notification"] is True


def test_send_rich_main_server_and_docker_messages_attach_nav_keyboards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[str | None] = []

    def _send_rich_bot_message(
        _bot: object,
        _chat_id: int,
        _html: str,
        *,
        nav_keyboard: str | None = None,
        **kwargs: object,
    ) -> dict[str, str]:
        del kwargs
        captured.append(nav_keyboard)
        return {"message_id": "1"}

    monkeypatch.setattr(rich_module, "send_rich_bot_message", _send_rich_bot_message)
    bot = cast(TeleBot, object())
    rich_module.send_rich_main_message(bot, 1, "<p>main</p>")
    rich_module.send_rich_server_message(bot, 1, "<p>server</p>")
    rich_module.send_rich_docker_message(bot, 1, "<p>docker</p>")
    assert captured == [NAV_MAIN, NAV_SERVER, NAV_DOCKER]


def test_edit_callback_message_text_supports_rich_message() -> None:
    bot = _EditBotStub()
    call = cast(object, _Call())
    rich = rich_module.build_rich_html_message("<h2>edited</h2>")
    markup = InlineKeyboardMarkup()

    was_edited = inline_common_module.edit_callback_message_text(
        call,  # type: ignore[arg-type]
        bot,  # type: ignore[arg-type]
        rich_message=rich,
        reply_markup=markup,
    )
    assert was_edited is True
    assert len(bot.edits) == 1
    assert bot.edits[0]["rich_message"] is rich
    assert bot.edits[0]["reply_markup"] is markup
    assert "text" not in bot.edits[0]
    assert "parse_mode" not in bot.edits[0]


def test_edit_callback_message_text_rejects_mixed_content() -> None:
    bot = _EditBotStub()
    call = cast(object, _Call())
    rich = rich_module.build_rich_html_message("<p>x</p>")
    with pytest.raises(ValueError, match="either text or rich_message"):
        inline_common_module.edit_callback_message_text(
            call,  # type: ignore[arg-type]
            bot,  # type: ignore[arg-type]
            text="classic",
            rich_message=rich,
        )


def test_edit_callback_message_text_requires_content() -> None:
    bot = _EditBotStub()
    call = cast(object, _Call())
    with pytest.raises(ValueError, match="required"):
        inline_common_module.edit_callback_message_text(
            call,  # type: ignore[arg-type]
            bot,  # type: ignore[arg-type]
        )


class _RichMessageTarget:
    chat = _Chat()
    message_id = 23
    content_type = "rich_message"


class _RichCall:
    id = "cb-2"
    message = _RichMessageTarget()


class _RejectingRichBotStub(_RichBotStub):
    def send_rich_message(self, **kwargs: Any) -> dict[str, Any]:
        del kwargs
        raise _RichRejected()


class _RichRejected(ApiTelegramException):
    def __init__(self) -> None:
        Exception.__init__(self, "Bad Request: can't parse rich message")
        self.error_code = 400
        self.description = "Bad Request: can't parse rich message"


def test_build_rich_html_message_wraps_plain_text() -> None:
    rich = rich_module.build_rich_html_message("Disk full & hot\nRetry later")
    assert rich.html == "<p>Disk full &amp; hot</p><p>Retry later</p>"


def test_build_rich_html_message_trims_oversized_tables() -> None:
    rows = "".join(f"<tr><td>{index}</td></tr>" for index in range(900))
    rich = rich_module.build_rich_html_message(
        f"<p><b>Title</b></p><table bordered striped>{rows}</table>"
    )
    assert rich.html is not None
    assert rich.html.endswith(
        "</table><p><i>Output truncated to fit Telegram limits.</i></p>"
    )
    assert rich.html.count("<tr>") < 500


def test_send_rich_bot_message_falls_back_to_plain_text_on_rejection() -> None:
    bot = _RejectingRichBotStub()
    rich_module.send_rich_bot_message(
        bot,  # type: ignore[arg-type]
        5,
        "<p><b>CPU</b></p><table><tr><th>Metric</th><th>Value</th></tr>"
        "<tr><td>Load</td><td>12%</td></tr></table>",
        disable_notification=True,
        message_effect_id="effect",
    )
    assert bot.rich_messages == []
    assert len(bot.messages) == 1
    assert bot.messages[0]["text"] == "CPU\nMetric | Value\nLoad | 12%"
    assert bot.messages[0]["disable_notification"] is True
    assert "message_effect_id" not in bot.messages[0]
    assert "parse_mode" not in bot.messages[0]


def test_send_rich_bot_message_reraises_non_content_errors() -> None:
    class _RateLimited(ApiTelegramException):
        def __init__(self) -> None:
            Exception.__init__(self, "Too Many Requests")
            self.error_code = 429

    class _Bot(_RichBotStub):
        def send_rich_message(self, **kwargs: Any) -> dict[str, Any]:
            del kwargs
            raise _RateLimited()

    with pytest.raises(_RateLimited):
        rich_module.send_rich_bot_message(_Bot(), 5, "<p>x</p>")  # type: ignore[arg-type]


def test_edit_callback_message_text_keeps_rich_lifecycle_for_classic_text() -> None:
    bot = _EditBotStub()
    was_edited = inline_common_module.edit_callback_message_text(
        cast(Any, _RichCall()),
        bot,  # type: ignore[arg-type]
        text="<b>Restarted</b>\nState: running",
        parse_mode="HTML",
    )
    assert was_edited is True
    assert "text" not in bot.edits[0]
    assert "parse_mode" not in bot.edits[0]
    rich = bot.edits[0]["rich_message"]
    assert isinstance(rich, InputRichMessage)
    assert rich.html == "<p>Restarted</p><p>State: running</p>"


def test_send_rich_bot_message_reraises_non_content_bad_requests() -> None:
    class _ChatNotFound(ApiTelegramException):
        def __init__(self) -> None:
            Exception.__init__(self, "Bad Request: chat not found")
            self.error_code = 400
            self.description = "Bad Request: chat not found"

    class _Bot(_RichBotStub):
        def send_rich_message(self, **kwargs: Any) -> dict[str, Any]:
            del kwargs
            raise _ChatNotFound()

    bot = _Bot()
    with pytest.raises(_ChatNotFound):
        rich_module.send_rich_bot_message(bot, 5, "<p>x</p>")  # type: ignore[arg-type]
    assert bot.messages == []


class _RejectingRichEditBotStub(_EditBotStub):
    def edit_message_text(self, **kwargs: Any) -> dict[str, Any]:
        if "rich_message" in kwargs:
            raise _RichRejected()
        return super().edit_message_text(**kwargs)


def test_edit_callback_message_text_falls_back_to_plain_text_on_rejection() -> None:
    bot = _RejectingRichEditBotStub()
    markup = InlineKeyboardMarkup()
    rich = rich_module.build_rich_html_message("<p><b>CPU</b></p><p>Load 5 &amp; 7</p>")

    was_edited = inline_common_module.edit_callback_message_text(
        cast(Any, _Call()),
        cast(Any, bot),
        rich_message=rich,
        reply_markup=markup,
    )

    assert was_edited is True
    assert bot.edits == [
        {
            "chat_id": 11,
            "message_id": 22,
            "text": "CPU\nLoad 5 & 7",
            "reply_markup": markup,
        }
    ]


def test_edit_callback_message_text_treats_not_modified_rich_edit_as_no_op() -> None:
    class _NotModified(ApiTelegramException):
        def __init__(self) -> None:
            Exception.__init__(self, "Bad Request: message is not modified")
            self.error_code = 400
            self.description = "Bad Request: message is not modified"

    class _Bot(_EditBotStub):
        def edit_message_text(self, **kwargs: Any) -> dict[str, Any]:
            del kwargs
            raise _NotModified()

    bot = _Bot()
    was_edited = inline_common_module.edit_callback_message_text(
        cast(Any, _Call()),
        cast(Any, bot),
        rich_message=rich_module.build_rich_html_message("<p>x</p>"),
    )

    assert was_edited is False
    assert bot.edits == []
    assert bot.callback_answers == [
        {
            "callback_query_id": "cb-1",
            "text": "Already up to date.",
            "show_alert": False,
        }
    ]
