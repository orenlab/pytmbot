from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Literal, cast

import pytest
from telebot import TeleBot
from telebot.types import CallbackQuery, Message

import pytmbot.handlers.bot_handlers.getmyid as getmyid_module
import pytmbot.handlers.bot_handlers.inline.update as inline_update_module
import pytmbot.handlers.bot_handlers.plugins as plugins_module
import pytmbot.handlers.bot_handlers.updates as updates_module
from pytmbot import exceptions
from pytmbot.utils.message_deletion import DeletionResult, DeletionStatus


@dataclass
class _User:
    id: int = 101
    first_name: str | None = "Test"
    last_name: str | None = "User"
    username: str | None = "test_user"


@dataclass
class _Chat:
    id: int = 202
    type: str = "private"
    title: str | None = None


@dataclass
class _Message:
    chat: _Chat = field(default_factory=_Chat)
    from_user: _User | None = field(default_factory=_User)
    message_id: int = 303


@dataclass
class _Call:
    id: str = "cb-1"
    data: str | None = None
    from_user: _User | None = field(default_factory=_User)
    message: _Message | None = field(default_factory=_Message)


@dataclass
class _SentMessage:
    message_id: int


@dataclass
class _Bot:
    sent_messages: list[dict[str, object]] = field(default_factory=list)
    callback_answers: list[dict[str, object]] = field(default_factory=list)
    edited_messages: list[dict[str, object]] = field(default_factory=list)
    chat_actions: list[tuple[int, str]] = field(default_factory=list)
    admin_ids: list[int] = field(default_factory=list)

    def send_chat_action(self, chat_id: int, action: str) -> bool:
        self.chat_actions.append((chat_id, action))
        return True

    def send_message(self, chat_id: int, text: str, **kwargs: object) -> _SentMessage:
        payload: dict[str, object] = {"chat_id": chat_id, "text": text, **kwargs}
        self.sent_messages.append(payload)
        return _SentMessage(message_id=1000 + len(self.sent_messages))

    def answer_callback_query(self, callback_query_id: str, **kwargs: object) -> str:
        payload: dict[str, object] = {
            "callback_query_id": callback_query_id,
            **kwargs,
        }
        self.callback_answers.append(payload)
        return "ok"

    def edit_message_text(self, **kwargs: object) -> str:
        self.edited_messages.append(kwargs)
        return "edited"


def _raw_handler(handler: object) -> Callable[..., object]:
    first_layer = getattr(handler, "__wrapped__", handler)
    second_layer = getattr(first_layer, "__wrapped__", first_layer)
    return cast(Callable[..., object], second_layer)


def test_getmyid_deletion_callback_logs_statuses(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    @dataclass
    class _LoggerStub:
        def debug(self, message: str, **kwargs: object) -> None:
            del kwargs
            events.append(message)

        def warning(self, message: str, **kwargs: object) -> None:
            del kwargs
            events.append(message)

    monkeypatch.setattr(getmyid_module, "logger", _LoggerStub())

    getmyid_module._deletion_callback(
        DeletionResult(
            status=DeletionStatus.SUCCESS,
            message_id=1,
            user_id=10,
            pending_count=0,
        )
    )
    getmyid_module._deletion_callback(
        DeletionResult(
            status=DeletionStatus.FAILED,
            message_id=1,
            user_id=10,
            pending_count=0,
            error_message="fail",
        )
    )

    assert "bot.handler.bot.getmyid.deleted.user.ok" in events
    assert "bot.handler.bot.getmyid.delete.user.fail" in events


def test_handle_getmyid_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = _Bot()
    handler = _raw_handler(getmyid_module.handle_getmyid)

    missing_user_message = _Message(from_user=None)
    result = handler(cast(Message, missing_user_message), cast(TeleBot, bot))
    assert result is None
    assert "Unable to resolve user identity" in str(bot.sent_messages[-1]["text"])

    schedule_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        getmyid_module.Compiler,
        "quick_render",
        lambda **kwargs: "compiled-getmyid",
    )

    def _scheduled(**kwargs: object) -> DeletionResult:
        schedule_calls.append(kwargs)
        message_id = cast(int, kwargs["message_id"])
        user_id = cast(int, kwargs["user_id"])
        return DeletionResult(
            status=DeletionStatus.SCHEDULED,
            message_id=message_id,
            user_id=user_id,
            pending_count=1,
        )

    monkeypatch.setattr(getmyid_module.deletion_manager, "schedule_deletion", _scheduled)

    normal_message = _Message()
    sent = handler(cast(Message, normal_message), cast(TeleBot, bot), auto_delete_delay=15)
    assert isinstance(sent, _SentMessage)
    assert schedule_calls and schedule_calls[-1]["delay_seconds"] == 15
    assert bot.chat_actions[-1] == (normal_message.chat.id, "typing")

    def _limited(**kwargs: object) -> DeletionResult:
        message_id = cast(int, kwargs["message_id"])
        user_id = cast(int, kwargs["user_id"])
        return DeletionResult(
            status=DeletionStatus.LIMIT_EXCEEDED,
            message_id=message_id,
            user_id=user_id,
            pending_count=3,
            error_message="limit",
        )

    monkeypatch.setattr(getmyid_module.deletion_manager, "schedule_deletion", _limited)
    sent_limit = handler(cast(Message, _Message()), cast(TeleBot, bot))
    assert isinstance(sent_limit, _SentMessage)
    assert "Privacy Notice" in str(bot.sent_messages[-1]["text"])


def test_handle_getmyid_raises_handling_exception_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _Bot()
    handler = _raw_handler(getmyid_module.handle_getmyid)

    monkeypatch.setattr(
        getmyid_module.Compiler,
        "quick_render",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("render fail")),
    )

    with pytest.raises(exceptions.HandlingException) as exc_info:
        handler(cast(Message, _Message()), cast(TeleBot, bot))

    assert exc_info.value.context.error_code == "HAND_015"
    assert "retrieving ID information" in str(bot.sent_messages[-1]["text"])


def test_handle_plugins_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    sent_payloads: list[dict[str, object]] = []
    bot = _Bot()
    handler = _raw_handler(plugins_module.handle_plugins)

    @dataclass
    class _PluginManagerStub:
        keys: list[str]
        names: list[str]
        descriptions: dict[str, str]

        def get_merged_index_keys(self) -> list[str]:
            return self.keys

        def get_plugin_names(self) -> list[str]:
            return self.names

        def get_plugin_descriptions(self) -> dict[str, str]:
            return self.descriptions

    manager_stub = _PluginManagerStub(keys=[], names=[], descriptions={})
    monkeypatch.setattr(plugins_module, "plugin_manager", manager_stub)

    monkeypatch.setattr(
        plugins_module,
        "send_telegram_message",
        lambda **kwargs: sent_payloads.append(kwargs),
    )

    handler(cast(Message, _Message()), cast(TeleBot, bot))
    assert sent_payloads and "no plugins available" in str(sent_payloads[-1]["text"])

    manager_stub.keys = ["A"]
    manager_stub.names = ["A"]
    manager_stub.descriptions = {"A": "desc"}
    monkeypatch.setattr(
        plugins_module,
        "keyboards",
        cast(
            object,
            type(
                "_Kbd",
                (),
                {"build_reply_keyboard": staticmethod(lambda plugin_keyboard_data=None: "plugins-kbd")},
            )(),
        ),
    )
    monkeypatch.setattr(plugins_module.Compiler, "quick_render", lambda **kwargs: "plugins-rendered")
    monkeypatch.setattr(plugins_module, "em", cast(object, type("_Em", (), {"get_emoji": staticmethod(lambda _key: "💭")})()))

    handler(cast(Message, _Message()), cast(TeleBot, bot))
    assert sent_payloads[-1]["text"] == "plugins-rendered"

    monkeypatch.setattr(
        manager_stub,
        "get_merged_index_keys",
        lambda: (_ for _ in ()).throw(RuntimeError("plugins fail")),
    )
    with pytest.raises(exceptions.HandlingException) as exc_info:
        handler(cast(Message, _Message()), cast(TeleBot, bot))

    assert exc_info.value.context.error_code == "HAND_015"
    assert "plugins command" in str(bot.sent_messages[-1]["text"])


def test_version_helpers_and_process_message_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert updates_module._normalize_version(" v1.2.3 ") == "1.2.3"
    assert updates_module._compare_versions("v1.2.4", "1.2.3") == 1
    assert updates_module._compare_versions("1.2.3", "1.2.3") == 0
    assert updates_module._compare_versions("bad-tag", "another") in (1, -1, 0)

    monkeypatch.setattr(updates_module, "is_bot_development", lambda version: True)
    monkeypatch.setattr(updates_module, "_render_development_message", lambda: "dev")
    assert updates_module._process_message() == ("dev", False)

    monkeypatch.setattr(updates_module, "is_bot_development", lambda version: False)
    monkeypatch.setattr(updates_module, "__check_bot_update", lambda: {})
    monkeypatch.setattr(updates_module, "_render_update_difficulties_message", lambda: "difficult")
    assert updates_module._process_message() == ("difficult", False)

    monkeypatch.setattr(
        updates_module,
        "__check_bot_update",
        lambda: {
            "tag_name": "2.0.0",
            "published_at": "2026-02-17, 10:00:00",
            "body": "notes",
        },
    )
    monkeypatch.setattr(updates_module, "_render_new_update_message", lambda context: "new")
    monkeypatch.setattr(updates_module, "_render_no_update_message", lambda: "same")
    monkeypatch.setattr(updates_module, "_render_future_message", lambda context: "future")

    monkeypatch.setattr(updates_module, "_compare_versions", lambda left, right: 1)
    assert updates_module._process_message() == ("new", True)

    monkeypatch.setattr(updates_module, "_compare_versions", lambda left, right: 0)
    assert updates_module._process_message() == ("same", False)

    monkeypatch.setattr(updates_module, "_compare_versions", lambda left, right: -1)
    assert updates_module._process_message() == ("future", False)


def test_check_bot_update_success_and_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Response:
        def __init__(self, payload: dict[str, str]) -> None:
            self._payload = payload

        def __enter__(self) -> _Response:
            return self

        def __exit__(
            self, exc_type: object, exc: object, tb: object
        ) -> Literal[False]:
            return False

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return self._payload

    payload = {
        "tag_name": "v1.2.3",
        "published_at": "2026-02-17T12:34:56",
        "body": "Release notes",
    }
    monkeypatch.setattr(updates_module.requests, "get", lambda url, timeout: _Response(payload))

    result = updates_module.__check_bot_update()
    assert result["tag_name"] == "v1.2.3"
    assert result["published_at"] == "2026-02-17, 12:34:56"

    monkeypatch.setattr(
        updates_module.requests,
        "get",
        lambda url, timeout: (_ for _ in ()).throw(updates_module.requests.RequestException("boom")),
    )
    assert updates_module.__check_bot_update() == {}


def test_handle_bot_updates_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    sent_payloads: list[dict[str, object]] = []
    bot = _Bot()
    handler = _raw_handler(updates_module.handle_bot_updates)

    monkeypatch.setattr(updates_module, "_process_message", lambda: ("update-message", True))
    monkeypatch.setattr(updates_module, "button_data", lambda text, callback_data: {"text": text, "callback_data": callback_data})
    monkeypatch.setattr(
        updates_module,
        "keyboards",
        cast(object, type("_Kbd", (), {"build_inline_keyboard": staticmethod(lambda buttons: buttons)})()),
    )
    monkeypatch.setattr(
        updates_module,
        "send_telegram_message",
        lambda **kwargs: sent_payloads.append(kwargs),
    )

    handler(cast(Message, _Message()), cast(TeleBot, bot))
    markup = cast(list[dict[str, str]], sent_payloads[-1]["reply_markup"])
    assert markup[0]["callback_data"] == "__how_update__:101"

    handler(cast(Message, _Message(from_user=None)), cast(TeleBot, bot))
    markup_without_user = cast(list[dict[str, str]], sent_payloads[-1]["reply_markup"])
    assert markup_without_user[0]["callback_data"] == "__how_update__"

    monkeypatch.setattr(
        updates_module,
        "send_telegram_message",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("send fail")),
    )
    with pytest.raises(exceptions.HandlingException) as exc_info:
        handler(cast(Message, _Message()), cast(TeleBot, bot))
    assert exc_info.value.context.error_code == "HAND_013"


def test_handle_update_info_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = _Bot()
    handler = _raw_handler(inline_update_module.handle_update_info)

    monkeypatch.setattr(
        inline_update_module,
        "parse_callback_target_user",
        lambda data, prefix: (_ for _ in ()).throw(ValueError("bad")),
    )
    handler(cast(CallbackQuery, _Call(data="bad")), cast(TeleBot, bot))
    assert "Invalid update info request format" in str(bot.callback_answers[-1]["text"])

    monkeypatch.setattr(inline_update_module, "parse_callback_target_user", lambda data, prefix: 101)
    monkeypatch.setattr(
        inline_update_module,
        "authorize_callback_request",
        lambda call, target_user_id, require_owner_match: (False, "denied"),
    )
    handler(cast(CallbackQuery, _Call(data="__how_update__:101")), cast(TeleBot, bot))
    assert bot.callback_answers[-1]["text"] == "denied"

    monkeypatch.setattr(
        inline_update_module,
        "authorize_callback_request",
        lambda call, target_user_id, require_owner_match: (True, ""),
    )
    handler(
        cast(CallbackQuery, _Call(data="__how_update__:101", message=None)),
        cast(TeleBot, bot),
    )
    assert "Cannot render update info" in str(bot.callback_answers[-1]["text"])

    monkeypatch.setattr(inline_update_module.Compiler, "quick_render", lambda **kwargs: "how-to-update")
    handler(cast(CallbackQuery, _Call(data="__how_update__:101")), cast(TeleBot, bot))
    assert bot.edited_messages[-1]["text"] == "how-to-update"

    monkeypatch.setattr(
        inline_update_module.Compiler,
        "quick_render",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("render fail")),
    )
    with pytest.raises(exceptions.HandlingException) as exc_info:
        handler(cast(CallbackQuery, _Call(data="__how_update__:101")), cast(TeleBot, bot))
    assert exc_info.value.context.error_code == "HAND_019"
    assert "Some error occurred" in str(bot.edited_messages[-1]["text"])
