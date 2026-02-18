from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import cast

import pytest
from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, Message, ReplyKeyboardMarkup

import pytmbot.handlers.auth_processing.auth_processing as auth_module
import pytmbot.handlers.auth_processing.qrcode_processing as qrcode_module
import pytmbot.handlers.auth_processing.twofa_processing as twofa_module
from pytmbot import exceptions
from pytmbot.utils.message_deletion import DeletionResult, DeletionStatus


@dataclass
class _User:
    id: int = 11
    first_name: str | None = "User"
    username: str | None = "user_name"


@dataclass
class _Chat:
    id: int = 22
    type: str = "private"


@dataclass
class _Msg:
    chat: _Chat = field(default_factory=_Chat)
    from_user: _User | None = field(default_factory=_User)
    text: str | None = None
    message_id: int = 33


@dataclass
class _Callback:
    message: _Msg | None = field(default_factory=_Msg)
    from_user: _User | None = field(default_factory=_User)
    data: str | None = None


@dataclass
class _Sent:
    message_id: int = 99


@dataclass
class _Bot:
    sent_messages: list[dict[str, object]] = field(default_factory=list)
    replies: list[dict[str, object]] = field(default_factory=list)
    actions: list[tuple[int, str]] = field(default_factory=list)
    deleted: list[tuple[int, int]] = field(default_factory=list)
    sent_photos: list[dict[str, object]] = field(default_factory=list)

    def send_message(self, chat_id: int, text: str, **kwargs: object) -> _Sent:
        self.sent_messages.append({"chat_id": chat_id, "text": text, **kwargs})
        return _Sent()

    def reply_to(self, message: _Msg, text: str, **kwargs: object) -> _Sent:
        self.replies.append({"message_id": message.message_id, "text": text, **kwargs})
        return _Sent()

    def send_chat_action(self, chat_id: int, action: str) -> bool:
        self.actions.append((chat_id, action))
        return True

    def delete_message(self, chat_id: int, message_id: int) -> bool:
        self.deleted.append((chat_id, message_id))
        return True

    def send_photo(self, chat_id: int, photo: object, **kwargs: object) -> _Sent:
        self.sent_photos.append({"chat_id": chat_id, "photo": photo, **kwargs})
        return _Sent(message_id=123)


@dataclass
class _StateFabric:
    PROCESSING: str = "processing"
    AUTHENTICATED: str = "authenticated"
    BLOCKED: str = "blocked"


@dataclass
class _SessionManagerStub:
    state_fabric: _StateFabric = field(default_factory=_StateFabric)
    blocked_users: set[int] = field(default_factory=set)
    auth_states: dict[int, str] = field(default_factory=dict)
    attempts: dict[int, int] = field(default_factory=dict)
    blocked_until: dict[int, datetime] = field(default_factory=dict)
    referer_uri: str | None = None
    handler_type: str = "message"
    login_set: list[int] = field(default_factory=list)
    referer_reset: list[int] = field(default_factory=list)

    def is_blocked(self, user_id: int) -> bool:
        return user_id in self.blocked_users

    def set_auth_state(self, user_id: int, state: str) -> None:
        self.auth_states[user_id] = state

    def get_auth_state(self, user_id: int) -> str:
        return self.auth_states.get(user_id, "idle")

    def get_blocked_time(self, user_id: int) -> datetime | None:
        return self.blocked_until.get(user_id)

    def set_blocked_time(self, user_id: int) -> None:
        self.blocked_until[user_id] = datetime.now() + timedelta(minutes=1)

    def get_totp_attempts(self, user_id: int) -> int:
        return self.attempts.get(user_id, 0)

    def increment_totp_attempts(self, user_id: int) -> None:
        self.attempts[user_id] = self.attempts.get(user_id, 0) + 1

    def reset_totp_attempts(self, user_id: int) -> None:
        self.attempts[user_id] = 0

    def set_login_time(self, user_id: int) -> None:
        self.login_set.append(user_id)

    def get_handler_type(self, user_id: int) -> str:
        del user_id
        return self.handler_type

    def get_referer_uri(self, user_id: int) -> str | None:
        del user_id
        return self.referer_uri

    def reset_referer_data(self, user_id: int) -> None:
        self.referer_reset.append(user_id)


def _raw_session_handler(handler: object) -> Callable[[Message, TeleBot], None]:
    raw = getattr(handler, "__wrapped__", handler)
    return cast(Callable[[Message, TeleBot], None], raw)


def _raw_qr_handler(
    handler: object,
) -> Callable[[Message, TeleBot, int], Message | None]:
    raw = getattr(handler, "__wrapped__", handler)
    return cast(Callable[[Message, TeleBot, int], Message | None], raw)


def test_auth_helpers_get_user_name_and_send_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_module, "Message", _Msg)
    monkeypatch.setattr(auth_module, "CallbackQuery", _Callback)

    msg = _Msg(from_user=_User(first_name="Denis", username="den"))
    assert auth_module._get_user_name(cast(Message, msg)) == "Denis"
    assert auth_module._get_user_name(cast(Message, _Msg(from_user=None))) == "User"

    bot = _Bot()
    auth_module._send_response(
        cast(Message, msg),
        cast(TeleBot, bot),
        "hello",
        cast(ReplyKeyboardMarkup, "kbd"),
    )
    assert bot.sent_messages[0]["text"] == "hello"

    callback = _Callback(message=_Msg(chat=_Chat(id=555), message_id=777))
    auth_module._send_response(
        cast(Message, callback),
        cast(TeleBot, bot),
        "cb",
        cast(InlineKeyboardMarkup, "kbd"),
    )
    assert bot.deleted[-1] == (555, 777)


def test_auth_handle_message_success_and_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(auth_module, "Message", _Msg)
    monkeypatch.setattr(auth_module, "CallbackQuery", _Callback)
    monkeypatch.setattr(
        auth_module,
        "keyboards",
        SimpleNamespace(
            build_reply_keyboard=lambda keyboard_type: f"kbd:{keyboard_type}"
        ),
    )
    monkeypatch.setattr(
        auth_module.Compiler,
        "quick_render",
        lambda template_name, name, **kwargs: f"{template_name}:{name}",
    )
    monkeypatch.setattr(
        auth_module, "_send_response", lambda query, bot, response, keyboard: None
    )

    auth_module._handle_auth_message(
        query=cast(Message, _Msg()),
        bot=cast(TeleBot, _Bot()),
        template_name="tpl",
        keyboard_type="auth",
        emojis={},
        error_code="AUTH_001",
        error_message="failed",
    )

    with pytest.raises(NotImplementedError):
        auth_module._handle_auth_message(
            query=cast(Message, object()),
            bot=cast(TeleBot, _Bot()),
            template_name="tpl",
            keyboard_type="auth",
            emojis={},
            error_code="AUTH_001",
            error_message="failed",
        )

    monkeypatch.setattr(
        auth_module.Compiler,
        "quick_render",
        lambda template_name, name, **kwargs: (_ for _ in ()).throw(
            RuntimeError("boom")
        ),
    )
    with pytest.raises(exceptions.AuthError) as exc_info:
        auth_module._handle_auth_message(
            query=cast(Message, _Msg()),
            bot=cast(TeleBot, _Bot()),
            template_name="tpl",
            keyboard_type="auth",
            emojis={},
            error_code="AUTH_001",
            error_message="failed",
        )
    assert exc_info.value.context.error_code == "AUTH_001"


def test_auth_public_handlers_delegate(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[tuple[str, str]] = []

    def _capture(**kwargs: object) -> None:
        called.append((str(kwargs["template_name"]), str(kwargs["keyboard_type"])))

    monkeypatch.setattr(auth_module, "_handle_auth_message", _capture)
    monkeypatch.setattr(
        auth_module,
        "em",
        SimpleNamespace(get_emoji=lambda _name: "x"),
    )

    auth_module.handle_unauthorized_message(
        cast(Message, _Msg()), cast(TeleBot, _Bot())
    )
    auth_module.handle_access_denied(cast(Message, _Msg()), cast(TeleBot, _Bot()))
    assert called == [
        ("a_auth_required.jinja2", "auth_keyboard"),
        ("a_access_denied.jinja2", "back_keyboard"),
    ]


def test_twofa_extract_totp_code_formats() -> None:
    assert twofa_module._extract_totp_code(None) == ""
    assert twofa_module._extract_totp_code("  ") == ""
    assert twofa_module._extract_totp_code("123456") == "123456"
    assert twofa_module._extract_totp_code("/123456") == "123456"
    assert twofa_module._extract_totp_code("/123456@botname") == "123456"


def test_twofa_send_totp_code_message_private_and_group(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, object]] = []
    monkeypatch.setattr(
        twofa_module,
        "send_telegram_message",
        lambda **kwargs: captured.append(kwargs),
    )
    monkeypatch.setattr(
        twofa_module,
        "keyboards",
        SimpleNamespace(
            build_reply_keyboard=lambda keyboard_type: f"kbd:{keyboard_type}"
        ),
    )
    monkeypatch.setattr(
        twofa_module.Compiler,
        "quick_render",
        lambda template_name, name, **kwargs: f"totp:{name}",
    )
    monkeypatch.setattr(
        twofa_module, "em", SimpleNamespace(get_emoji=lambda _name: "e")
    )

    private_message = _Msg(
        chat=_Chat(id=1, type="private"), from_user=_User(first_name="Alice")
    )
    twofa_module._send_totp_code_message(
        cast(Message, private_message), cast(TeleBot, _Bot())
    )
    assert captured[-1]["reply_to_message_id"] is None

    group_message = _Msg(
        chat=_Chat(id=2, type="group"), from_user=_User(first_name="Bob")
    )
    twofa_module._send_totp_code_message(
        cast(Message, group_message), cast(TeleBot, _Bot())
    )
    assert captured[-1]["reply_to_message_id"] == group_message.message_id


def test_twofa_invalid_and_max_attempt_and_blocking_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_stub = _SessionManagerStub()
    monkeypatch.setattr(twofa_module, "session_manager", session_stub)

    bot = _Bot()
    message = _Msg(from_user=_User(id=7), text="bad-code")

    twofa_module._handle_invalid_totp_code(cast(Message, message), cast(TeleBot, bot))
    assert session_stub.attempts[7] == 1

    twofa_module._block_user(7)
    assert session_stub.auth_states[7] == session_stub.state_fabric.BLOCKED
    assert session_stub.attempts[7] == 0
    assert 7 in session_stub.blocked_until

    twofa_module._handle_max_attempts_reached(
        cast(Message, message), cast(TeleBot, bot)
    )
    assert "maximum number of attempts" in str(bot.replies[-1]["text"])


def test_twofa_create_referer_keyboard_and_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_stub = _SessionManagerStub()
    session_stub.referer_uri = "/docker"
    monkeypatch.setattr(twofa_module, "session_manager", session_stub)
    monkeypatch.setattr(
        twofa_module,
        "keyboards",
        SimpleNamespace(
            build_referer_main_keyboard=lambda referer_uri: f"main:{referer_uri}",
            build_referer_inline_keyboard=lambda referer_uri: f"inline:{referer_uri}",
        ),
    )

    session_stub.handler_type = "message"
    assert twofa_module.__create_referer_keyboard(1) == "main:/docker"

    session_stub.handler_type = "callback_query"
    assert twofa_module.__create_referer_keyboard(1) == "inline:/docker"

    session_stub.handler_type = "unsupported"
    with pytest.raises(exceptions.HandlingException):
        twofa_module.__create_referer_keyboard(1)
    assert session_stub.referer_reset[-1] == 1


def test_handle_twofa_message_and_totp_verification_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_stub = _SessionManagerStub()
    session_stub.auth_states[55] = session_stub.state_fabric.PROCESSING
    monkeypatch.setattr(twofa_module, "session_manager", session_stub)
    monkeypatch.setattr(
        twofa_module, "var_config", SimpleNamespace(totp_max_attempts=2)
    )
    monkeypatch.setattr(
        twofa_module, "is_valid_totp_code", lambda value: value == "123456"
    )
    monkeypatch.setattr(
        twofa_module, "em", SimpleNamespace(get_emoji=lambda _name: "e")
    )
    monkeypatch.setattr(
        twofa_module.Compiler,
        "quick_render",
        lambda template_name, emojis: "ok",
    )
    monkeypatch.setattr(
        twofa_module, "__create_referer_keyboard", lambda user_id: "kbd"
    )

    class _Authenticator:
        def __init__(self, user_id: int, username: str) -> None:
            del user_id, username

        def verify_totp_code(self, code: str) -> bool:
            return code == "123456"

    monkeypatch.setattr(twofa_module, "TwoFactorAuthenticator", _Authenticator)

    blocked_called: list[int] = []
    invalid_called: list[int] = []
    max_called: list[int] = []

    monkeypatch.setattr(
        twofa_module,
        "_handle_blocked_user",
        lambda message, bot: blocked_called.append(1),
    )
    monkeypatch.setattr(
        twofa_module,
        "_handle_invalid_totp_code",
        lambda message, bot: invalid_called.append(1),
    )
    monkeypatch.setattr(
        twofa_module,
        "_handle_max_attempts_reached",
        lambda message, bot: max_called.append(1),
    )

    raw_twofa = _raw_session_handler(twofa_module.handle_twofa_message)
    raw_verify = _raw_session_handler(twofa_module.handle_totp_code_verification)
    bot = _Bot()

    # handle_twofa_message with blocked user.
    blocked_msg = _Msg(from_user=_User(id=77))
    session_stub.blocked_users.add(77)
    raw_twofa(cast(Message, blocked_msg), cast(TeleBot, bot))
    assert blocked_called

    # invalid code branch.
    invalid_msg = _Msg(from_user=_User(id=55), text="111")
    raw_verify(cast(Message, invalid_msg), cast(TeleBot, bot))
    assert invalid_called

    # max attempts branch.
    session_stub.attempts[55] = 3
    valid_msg = _Msg(from_user=_User(id=55), text="123456")
    raw_verify(cast(Message, valid_msg), cast(TeleBot, bot))
    assert max_called

    # success branch.
    session_stub.attempts[55] = 0
    session_stub.blocked_until.pop(55, None)
    raw_verify(cast(Message, valid_msg), cast(TeleBot, bot))
    assert session_stub.auth_states[55] == session_stub.state_fabric.AUTHENTICATED
    assert session_stub.login_set == [55]


def test_qrcode_handler_success_limit_and_failure_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        qrcode_module,
        "keyboards",
        SimpleNamespace(build_reply_keyboard=lambda keyboard_type: "kbd"),
    )
    monkeypatch.setattr(
        qrcode_module,
        "em",
        SimpleNamespace(get_emoji=lambda _name: "e"),
    )
    monkeypatch.setattr(
        qrcode_module.Compiler,
        "quick_render",
        lambda template_name, context, **kwargs: f"error:{context}",
    )

    class _Authenticator:
        def __init__(self, user_id: int, username: str) -> None:
            del user_id, username

        def generate_totp_qr_code(self) -> bytes | None:
            return b"qr-bytes"

    monkeypatch.setattr(qrcode_module, "TwoFactorAuthenticator", _Authenticator)

    scheduled = DeletionResult(
        status=DeletionStatus.SCHEDULED,
        message_id=123,
        user_id=11,
        pending_count=1,
    )
    monkeypatch.setattr(
        qrcode_module.deletion_manager, "schedule_deletion", lambda **kwargs: scheduled
    )

    raw_qr = _raw_qr_handler(qrcode_module.handle_qr_code_message)
    bot = _Bot()
    message = _Msg(from_user=_User(id=11), chat=_Chat(id=1))
    sent = raw_qr(cast(Message, message), cast(TeleBot, bot), 60)
    assert sent is not None
    assert bot.sent_photos

    limit_result = DeletionResult(
        status=DeletionStatus.LIMIT_EXCEEDED,
        message_id=123,
        user_id=11,
        pending_count=3,
    )
    monkeypatch.setattr(
        qrcode_module.deletion_manager,
        "schedule_deletion",
        lambda **kwargs: limit_result,
    )
    raw_qr(cast(Message, message), cast(TeleBot, bot), 60)
    assert any("Security Notice" in str(item["text"]) for item in bot.sent_messages)

    class _NoQrAuthenticator:
        def __init__(self, user_id: int, username: str) -> None:
            del user_id, username

        def generate_totp_qr_code(self) -> bytes | None:
            return None

    monkeypatch.setattr(qrcode_module, "TwoFactorAuthenticator", _NoQrAuthenticator)
    result = raw_qr(cast(Message, message), cast(TeleBot, bot), 60)
    assert result is None


def test_qrcode_handler_wraps_exceptions(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BrokenAuthenticator:
        def __init__(self, user_id: int, username: str) -> None:
            del user_id, username

        def generate_totp_qr_code(self) -> bytes | None:
            raise RuntimeError("qr broken")

    monkeypatch.setattr(qrcode_module, "TwoFactorAuthenticator", _BrokenAuthenticator)
    monkeypatch.setattr(
        qrcode_module,
        "keyboards",
        SimpleNamespace(build_reply_keyboard=lambda keyboard_type: "kbd"),
    )
    monkeypatch.setattr(
        qrcode_module.deletion_manager,
        "schedule_deletion",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("queue failed")),
    )

    raw_qr = _raw_qr_handler(qrcode_module.handle_qr_code_message)
    bot = _Bot()
    message = _Msg(from_user=_User(id=11), chat=_Chat(id=1))

    with pytest.raises(exceptions.HandlingException) as exc_info:
        raw_qr(cast(Message, message), cast(TeleBot, bot), 60)
    assert exc_info.value.context.error_code == "HAND_021"
