from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import cast

import pytest
from telebot import TeleBot
from telebot.types import (
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardMarkup,
    ReplyParameters,
)

import pytmbot.handlers.auth_processing.auth_processing as auth_module
import pytmbot.handlers.auth_processing.qrcode_processing as qrcode_module
import pytmbot.handlers.auth_processing.twofa_processing as twofa_module
import pytmbot.utils.message_deletion as message_deletion_module
from pytmbot import exceptions
from pytmbot.parsers.compiler import Compiler
from pytmbot.utils.message_deletion import DeletionResult, DeletionStatus
from pytmbot.utils.totp import TOTPVerificationResult

type _PayloadValue = (
    str
    | int
    | float
    | bool
    | bytes
    | None
    | dict[str, _PayloadValue]
    | list[_PayloadValue]
)
type _PayloadDict = dict[str, _PayloadValue]
type _MessageHandler = Callable[[Message, TeleBot], None]
type _QrHandler = Callable[[Message, TeleBot, int], Message | None]
type _SessionRawInput = (
    Callable[..., Message | None]
    | Callable[..., None]
    | Callable[[Callable[..., Message | None]], Callable[..., Message | None]]
    | Callable[[Callable[..., None]], Callable[..., None]]
)
type _QrRawInput = (
    Callable[..., Message | None]
    | Callable[[Callable[..., Message | None]], Callable[..., Message | None]]
)


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


def _make_bot() -> SimpleNamespace:
    sent_messages: list[_PayloadDict] = []
    replies: list[_PayloadDict] = []
    actions: list[tuple[int, str]] = []
    deleted: list[tuple[int, int]] = []
    sent_photos: list[_PayloadDict] = []

    def send_message(chat_id: int, text: str, **kwargs: _PayloadValue) -> _Sent:
        sent_messages.append({"chat_id": chat_id, "text": text, **kwargs})
        return _Sent()

    def reply_to(message: _Msg, text: str, **kwargs: _PayloadValue) -> _Sent:
        replies.append({"message_id": message.message_id, "text": text, **kwargs})
        return _Sent()

    def send_chat_action(chat_id: int, action: str) -> bool:
        actions.append((chat_id, action))
        return True

    def delete_message(chat_id: int, message_id: int) -> bool:
        deleted.append((chat_id, message_id))
        return True

    def send_photo(
        chat_id: int, photo: _PayloadValue, **kwargs: _PayloadValue
    ) -> _Sent:
        sent_photos.append({"chat_id": chat_id, "photo": photo, **kwargs})
        return _Sent(message_id=123)

    return SimpleNamespace(
        sent_messages=sent_messages,
        replies=replies,
        actions=actions,
        deleted=deleted,
        sent_photos=sent_photos,
        send_message=send_message,
        reply_to=reply_to,
        send_chat_action=send_chat_action,
        delete_message=delete_message,
        send_photo=send_photo,
    )


@dataclass
class _StateFabric:
    PROCESSING: str = "processing"
    AUTHENTICATED: str = "authenticated"
    BLOCKED: str = "blocked"


def _make_session_manager_stub() -> SimpleNamespace:
    state_fabric = _StateFabric()
    blocked_users: set[int] = set()
    auth_states: dict[int, str] = {}
    attempts: dict[int, int] = {}
    blocked_until: dict[int, datetime] = {}
    login_set: list[int] = []
    referer_reset: list[int] = []

    session_manager = SimpleNamespace(
        state_fabric=state_fabric,
        blocked_users=blocked_users,
        auth_states=auth_states,
        attempts=attempts,
        blocked_until=blocked_until,
        referer_uri=None,
        handler_type="message",
        login_set=login_set,
        referer_reset=referer_reset,
    )

    def is_blocked(user_id: int) -> bool:
        return user_id in blocked_users

    def set_auth_state(user_id: int, state: str) -> None:
        auth_states[user_id] = state

    def get_auth_state(user_id: int) -> str:
        return auth_states.get(user_id, "idle")

    def get_blocked_time(user_id: int) -> datetime | None:
        return blocked_until.get(user_id)

    def set_blocked_time(user_id: int) -> None:
        blocked_until[user_id] = datetime.now() + timedelta(minutes=1)

    def get_totp_attempts(user_id: int) -> int:
        return attempts.get(user_id, 0)

    def increment_totp_attempts(user_id: int) -> None:
        attempts[user_id] = attempts.get(user_id, 0) + 1

    def reset_totp_attempts(user_id: int) -> None:
        attempts[user_id] = 0

    def set_login_time(user_id: int) -> None:
        login_set.append(user_id)

    def get_handler_type(user_id: int) -> str:
        del user_id
        return str(session_manager.handler_type)

    def get_referer_uri(user_id: int) -> str | None:
        del user_id
        return cast(str | None, session_manager.referer_uri)

    def reset_referer_data(user_id: int) -> None:
        referer_reset.append(user_id)

    session_manager.is_blocked = is_blocked
    session_manager.set_auth_state = set_auth_state
    session_manager.get_auth_state = get_auth_state
    session_manager.get_blocked_time = get_blocked_time
    session_manager.set_blocked_time = set_blocked_time
    session_manager.get_totp_attempts = get_totp_attempts
    session_manager.increment_totp_attempts = increment_totp_attempts
    session_manager.reset_totp_attempts = reset_totp_attempts
    session_manager.set_login_time = set_login_time
    session_manager.get_handler_type = get_handler_type
    session_manager.get_referer_uri = get_referer_uri
    session_manager.reset_referer_data = reset_referer_data
    return session_manager


def _processing_session(
    monkeypatch: pytest.MonkeyPatch, *, user_id: int
) -> SimpleNamespace:
    """Session stub with ``user_id`` waiting for a 2FA code, installed in 2FA."""
    session_stub = _make_session_manager_stub()
    session_stub.auth_states[user_id] = session_stub.state_fabric.PROCESSING
    monkeypatch.setattr(twofa_module, "session_manager", session_stub)
    return session_stub


def _raw_session_handler(handler: _SessionRawInput) -> _MessageHandler:
    raw = getattr(handler, "__wrapped__", handler)
    return cast(_MessageHandler, raw)


def _raw_qr_handler(handler: _QrRawInput) -> _QrHandler:
    raw = getattr(handler, "__wrapped__", handler)
    return cast(_QrHandler, raw)


def test_auth_helpers_get_user_name_and_send_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_module, "Message", _Msg)
    monkeypatch.setattr(auth_module, "CallbackQuery", _Callback)

    msg = _Msg(from_user=_User(first_name="Denis", username="den"))
    assert auth_module._get_user_name(cast(Message, msg)) == "Denis"
    assert auth_module._get_user_name(cast(Message, _Msg(from_user=None))) == "User"

    bot = _make_bot()
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
        Compiler,
        "quick_render",
        lambda template_name, name, **kwargs: f"{template_name}:{name}",
    )
    monkeypatch.setattr(
        auth_module, "_send_response", lambda query, bot, response, keyboard: None
    )

    auth_module._handle_auth_message(
        query=cast(Message, _Msg()),
        bot=cast(TeleBot, _make_bot()),
        template_name="tpl",
        keyboard_type="auth",
        emojis={},
        error_code="AUTH_001",
        error_message="failed",
    )

    with pytest.raises(NotImplementedError):
        auth_module._handle_auth_message(
            query=cast(Message, 123),
            bot=cast(TeleBot, _make_bot()),
            template_name="tpl",
            keyboard_type="auth",
            emojis={},
            error_code="AUTH_001",
            error_message="failed",
        )

    monkeypatch.setattr(
        Compiler,
        "quick_render",
        lambda template_name, name, **kwargs: (_ for _ in ()).throw(
            RuntimeError("boom")
        ),
    )
    with pytest.raises(exceptions.AuthError) as exc_info:
        auth_module._handle_auth_message(
            query=cast(Message, _Msg()),
            bot=cast(TeleBot, _make_bot()),
            template_name="tpl",
            keyboard_type="auth",
            emojis={},
            error_code="AUTH_001",
            error_message="failed",
        )
    assert exc_info.value.context.error_code == "AUTH_001"


def test_auth_public_handlers_delegate(monkeypatch: pytest.MonkeyPatch) -> None:
    called: list[tuple[str, str]] = []

    def _capture(**kwargs: _PayloadValue) -> None:
        called.append((str(kwargs["template_name"]), str(kwargs["keyboard_type"])))

    monkeypatch.setattr(auth_module, "_handle_auth_message", _capture)
    monkeypatch.setattr(
        auth_module,
        "em",
        SimpleNamespace(get_emoji=lambda _name: "x"),
    )

    auth_module.handle_unauthorized_message(
        cast(Message, _Msg()), cast(TeleBot, _make_bot())
    )
    auth_module.handle_access_denied(cast(Message, _Msg()), cast(TeleBot, _make_bot()))
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
    assert twofa_module._extract_totp_code("/help@botname") == ""


def test_twofa_send_totp_code_message_uses_back_keyboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[_PayloadDict] = []
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
        Compiler,
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
        cast(Message, private_message), cast(TeleBot, _make_bot())
    )
    # Codes are entered only in a private chat: no ForceReply, no reply-to.
    assert captured[-1]["text"] == "totp:Alice"
    assert captured[-1]["reply_markup"] == "kbd:back_keyboard"
    assert "reply_to_message_id" not in captured[-1]


def test_twofa_invalid_and_max_attempt_and_blocking_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_stub = _make_session_manager_stub()
    monkeypatch.setattr(twofa_module, "session_manager", session_stub)

    bot = _make_bot()
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
    session_stub = _make_session_manager_stub()
    session_stub.referer_uri = "/docker"
    monkeypatch.setattr(twofa_module, "session_manager", session_stub)
    monkeypatch.setattr(
        twofa_module,
        "keyboards",
        SimpleNamespace(
            build_referer_main_keyboard=lambda referer_uri: f"main:{referer_uri}",
            build_referer_inline_keyboard=lambda referer_uri, label=None: (
                f"inline:{referer_uri}|{label}"
            ),
            build_reply_keyboard=lambda: "main-menu",
        ),
    )

    session_stub.handler_type = "message"
    assert cast(str, twofa_module.__create_referer_keyboard(1)) == "main:/docker"

    session_stub.handler_type = "callback_query"
    assert cast(str, twofa_module.__create_referer_keyboard(1)) == "inline:/docker|None"

    # A stored Stop press returns to the Manage screen, never to Stop itself.
    session_stub.referer_uri = "__stop__:0123456789ab:1"
    assert cast(str, twofa_module.__create_referer_keyboard(1)) == (
        "inline:__manage__:0123456789ab:1|container actions"
    )

    # No pending action: confirm with the main menu instead of failing.
    session_stub.referer_uri = None
    assert cast(str, twofa_module.__create_referer_keyboard(1)) == "main-menu"
    session_stub.referer_uri = "/docker"

    session_stub.handler_type = "unsupported"
    with pytest.raises(exceptions.HandlingException):
        twofa_module.__create_referer_keyboard(1)
    assert session_stub.referer_reset[-1] == 1


def test_handle_twofa_message_and_totp_verification_branches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_stub = _make_session_manager_stub()
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
        Compiler,
        "quick_render",
        lambda template_name, emojis: "ok",
    )
    monkeypatch.setattr(
        twofa_module, "__create_referer_keyboard", lambda user_id: "kbd"
    )

    class _Authenticator:
        def __init__(self, user_id: int, username: str) -> None:
            del user_id, username

        def check_totp_code(self, code: str) -> TOTPVerificationResult:
            if code == "123456":
                return TOTPVerificationResult.VALID
            return TOTPVerificationResult.INVALID

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
    bot = _make_bot()

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

    # success branch: an earlier mistake must not carry over.
    session_stub.attempts[55] = 1
    session_stub.blocked_until.pop(55, None)
    raw_verify(cast(Message, valid_msg), cast(TeleBot, bot))
    assert session_stub.auth_states[55] == session_stub.state_fabric.AUTHENTICATED
    assert session_stub.login_set == [55]
    assert session_stub.attempts[55] == 0


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
        Compiler,
        "quick_render",
        lambda template_name, context, **kwargs: f"error:{context}",
    )

    class _Authenticator:
        def __init__(self, user_id: int, username: str) -> None:
            del user_id, username

        def generate_totp_qr_code(self) -> bytes | None:
            return b"qr-bytes"

    monkeypatch.setattr(qrcode_module, "TwoFactorAuthenticator", _Authenticator)
    monkeypatch.setattr(
        message_deletion_module.deletion_manager, "can_schedule", lambda user_id: True
    )

    scheduled = DeletionResult(
        status=DeletionStatus.SCHEDULED,
        message_id=123,
        user_id=11,
        pending_count=1,
    )
    monkeypatch.setattr(
        "pytmbot.handlers.auth_processing.qrcode_processing.deletion_manager.schedule_deletion",
        lambda **kwargs: scheduled,
    )

    raw_qr = _raw_qr_handler(qrcode_module.handle_qr_code_message)
    bot = _make_bot()
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
        "pytmbot.handlers.auth_processing.qrcode_processing.deletion_manager.schedule_deletion",
        lambda **kwargs: limit_result,
    )
    # Another deletion took the last slot: the QR code is removed at once.
    assert raw_qr(cast(Message, message), cast(TeleBot, bot), 60) is None
    assert bot.deleted == [(1, 123)]
    assert bot.sent_messages[-1]["text"] == qrcode_module.QR_NOT_SCHEDULED_TEXT
    assert not any("manually" in str(item["text"]) for item in bot.sent_messages)

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
        "pytmbot.handlers.auth_processing.qrcode_processing.deletion_manager.schedule_deletion",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("queue failed")),
    )

    raw_qr = _raw_qr_handler(qrcode_module.handle_qr_code_message)
    bot = _make_bot()
    message = _Msg(from_user=_User(id=11), chat=_Chat(id=1))

    with pytest.raises(exceptions.HandlingException) as exc_info:
        raw_qr(cast(Message, message), cast(TeleBot, bot), 60)
    assert exc_info.value.context.error_code == "HAND_021"


def test_qrcode_deletion_callback_sends_main_navigation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        message_deletion_module,
        "_build_post_delete_navigation_keyboard",
        lambda nav_keyboard="main_keyboard": "main-kbd",
    )
    bot = _make_bot()
    callback = message_deletion_module.create_post_delete_navigation_callback(
        qrcode_module._qr_deletion_callback,
        bot=cast(TeleBot, bot),
        chat_id=555,
        navigation_text=qrcode_module.QR_DELETED_NAVIGATION_TEXT,
    )
    callback(
        DeletionResult(
            status=DeletionStatus.SUCCESS,
            message_id=101,
            user_id=11,
            pending_count=0,
        ),
    )

    assert bot.sent_messages
    assert bot.sent_messages[-1]["chat_id"] == 555
    assert bot.sent_messages[-1]["reply_markup"] == "main-kbd"
    assert "deleted for security" in str(bot.sent_messages[-1]["text"])


_GROUP_CHAT_ID = -100500
_NOTICE_LINK = "https://t.me/pytmbot_test_bot?start=2fa"


def _group_message(
    *,
    user_id: int = 11,
    text: str | None = None,
    message_id: int = 40,
    chat_type: str = "supergroup",
) -> _Msg:
    return _Msg(
        chat=_Chat(id=_GROUP_CHAT_ID, type=chat_type),
        from_user=_User(id=user_id),
        text=text,
        message_id=message_id,
    )


def _make_bot_with_username() -> SimpleNamespace:
    bot = _make_bot()
    bot.user = SimpleNamespace(username="pytmbot_test_bot")
    return bot


def _assert_private_chat_notice(
    payload: _PayloadDict, *, reply_to: int, with_link: bool = True
) -> None:
    assert payload["chat_id"] == _GROUP_CHAT_ID
    assert "private chat" in str(payload["text"])
    reply_parameters = payload["reply_parameters"]
    assert isinstance(reply_parameters, ReplyParameters)
    assert reply_parameters.message_id == reply_to
    assert reply_parameters.allow_sending_without_reply is True
    markup = payload["reply_markup"]
    if not with_link:
        assert markup is None
        return
    assert isinstance(markup, InlineKeyboardMarkup)
    [[button]] = markup.keyboard
    assert button.text == auth_module.PRIVATE_CHAT_BUTTON_TEXT
    assert button.url == _NOTICE_LINK


def test_unauthorized_in_group_posts_only_a_private_chat_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(auth_module, "CallbackQuery", _Callback)
    bot = _make_bot_with_username()

    auth_module.handle_unauthorized_message(
        cast(Message, _group_message(text="Containers")), cast(TeleBot, bot)
    )
    # A press on the presser's own button: the group message stays as well.
    callback = _Callback(
        message=_group_message(message_id=41, chat_type="group"),
        data="__stop__:0123456789ab:11",
    )
    auth_module.handle_unauthorized_message(cast(Message, callback), cast(TeleBot, bot))

    assert bot.deleted == []
    assert len(bot.sent_messages) == 2
    _assert_private_chat_notice(bot.sent_messages[0], reply_to=40)
    _assert_private_chat_notice(bot.sent_messages[1], reply_to=41)


def test_private_chat_notice_without_bot_username_has_no_button() -> None:
    # Bot without a cached or fetchable identity (get_me unavailable).
    bot = _make_bot()
    auth_module.send_private_chat_notice(
        cast(TeleBot, bot), cast(Message, _group_message())
    )
    _assert_private_chat_notice(bot.sent_messages[-1], reply_to=40, with_link=False)
    assert "Open a private chat with the bot" in str(bot.sent_messages[-1]["text"])

    bot.user = SimpleNamespace(username=None)
    auth_module.send_private_chat_notice(
        cast(TeleBot, bot), cast(Message, _group_message())
    )
    _assert_private_chat_notice(bot.sent_messages[-1], reply_to=40, with_link=False)


def test_unauthorized_in_group_wraps_send_errors() -> None:
    bot = _make_bot_with_username()

    def _fail(chat_id: int, text: str, **kwargs: _PayloadValue) -> _Sent:
        del chat_id, text, kwargs
        raise RuntimeError("chat not found")

    bot.send_message = _fail
    with pytest.raises(exceptions.AuthError) as exc_info:
        auth_module.handle_unauthorized_message(
            cast(Message, _group_message()), cast(TeleBot, bot)
        )
    assert exc_info.value.context.error_code == "AUTH_001"


def test_enter_2fa_code_in_group_points_to_private_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_stub = _make_session_manager_stub()
    monkeypatch.setattr(twofa_module, "session_manager", session_stub)
    prompts: list[int] = []
    monkeypatch.setattr(
        twofa_module,
        "_send_totp_code_message",
        lambda message, bot: prompts.append(1),
    )
    bot = _make_bot_with_username()

    raw_twofa = _raw_session_handler(twofa_module.handle_twofa_message)
    raw_twofa(
        cast(Message, _group_message(user_id=55, text="Enter 2FA code")),
        cast(TeleBot, bot),
    )

    assert session_stub.auth_states == {}
    assert prompts == []
    _assert_private_chat_notice(bot.sent_messages[-1], reply_to=40)


def test_totp_code_in_group_is_removed_and_not_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_stub = _processing_session(monkeypatch, user_id=55)

    class _UnexpectedAuthenticator:
        def __init__(self, user_id: int, username: str | None) -> None:
            del user_id, username
            raise AssertionError("A code sent to a group must not be checked")

    monkeypatch.setattr(
        twofa_module, "TwoFactorAuthenticator", _UnexpectedAuthenticator
    )
    raw_verify = _raw_session_handler(twofa_module.handle_totp_code_verification)
    bot = _make_bot_with_username()

    raw_verify(
        cast(Message, _group_message(user_id=55, text="123456")), cast(TeleBot, bot)
    )

    assert bot.deleted == [(_GROUP_CHAT_ID, 40)]
    _assert_private_chat_notice(bot.sent_messages[-1], reply_to=40)
    assert session_stub.attempts == {}
    assert session_stub.auth_states[55] == session_stub.state_fabric.PROCESSING
    assert bot.replies == []

    # Without the right to delete members' messages the notice still goes out.
    def _forbidden(chat_id: int, message_id: int) -> bool:
        del chat_id, message_id
        raise RuntimeError("message can't be deleted")

    bot.delete_message = _forbidden
    raw_verify(
        cast(Message, _group_message(user_id=55, text="/123456", message_id=42)),
        cast(TeleBot, bot),
    )
    _assert_private_chat_notice(bot.sent_messages[-1], reply_to=42)
    assert session_stub.attempts == {}

    # Members who are not entering a code are ignored without group noise.
    sent_before = len(bot.sent_messages)
    raw_verify(
        cast(Message, _group_message(user_id=66, text="123456", message_id=43)),
        cast(TeleBot, bot),
    )
    assert len(bot.sent_messages) == sent_before


@pytest.mark.parametrize(
    ("result", "expected_attempts", "expected_reply"),
    [
        (
            TOTPVerificationResult.ISSUED_BEFORE_RESTART,
            0,
            twofa_module.TOTP_ISSUED_BEFORE_RESTART_TEXT,
        ),
        (
            TOTPVerificationResult.REPLAYED,
            1,
            "That 2FA code is invalid. Please try again.",
        ),
        (
            TOTPVerificationResult.INVALID,
            1,
            "That 2FA code is invalid. Please try again.",
        ),
    ],
)
def test_totp_rejections_count_only_the_users_mistakes(
    monkeypatch: pytest.MonkeyPatch,
    result: TOTPVerificationResult,
    expected_attempts: int,
    expected_reply: str,
) -> None:
    session_stub = _processing_session(monkeypatch, user_id=55)
    monkeypatch.setattr(twofa_module, "_totp_attempt_times", {})

    class _Authenticator:
        def __init__(self, user_id: int, username: str | None) -> None:
            del user_id, username

        def check_totp_code(self, code: str) -> TOTPVerificationResult:
            del code
            return result

    monkeypatch.setattr(twofa_module, "TwoFactorAuthenticator", _Authenticator)
    raw_verify = _raw_session_handler(twofa_module.handle_totp_code_verification)
    bot = _make_bot()

    raw_verify(
        cast(Message, _Msg(from_user=_User(id=55), text="123456")),
        cast(TeleBot, bot),
    )

    assert session_stub.attempts.get(55, 0) == expected_attempts
    assert bot.replies[-1]["text"] == expected_reply
    assert session_stub.auth_states[55] == session_stub.state_fabric.PROCESSING


def _install_qr_stubs(
    monkeypatch: pytest.MonkeyPatch,
    *,
    can_schedule: bool,
    schedule: Callable[..., DeletionResult],
) -> list[int]:
    generated: list[int] = []

    class _Authenticator:
        def __init__(self, user_id: int, username: str | None) -> None:
            del user_id, username

        def generate_totp_qr_code(self) -> bytes:
            generated.append(1)
            return b"qr-bytes"

    monkeypatch.setattr(qrcode_module, "TwoFactorAuthenticator", _Authenticator)
    monkeypatch.setattr(
        qrcode_module,
        "keyboards",
        SimpleNamespace(build_reply_keyboard=lambda keyboard_type: "kbd"),
    )
    monkeypatch.setattr(
        message_deletion_module.deletion_manager,
        "can_schedule",
        lambda user_id: can_schedule,
    )
    monkeypatch.setattr(
        message_deletion_module.deletion_manager, "schedule_deletion", schedule
    )
    return generated


def _unexpected_schedule(**kwargs: _PayloadValue) -> DeletionResult:
    del kwargs
    raise AssertionError("No QR code may be sent here")


def test_qr_code_in_group_posts_only_a_private_chat_link(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generated = _install_qr_stubs(
        monkeypatch, can_schedule=True, schedule=_unexpected_schedule
    )
    bot = _make_bot_with_username()

    raw_qr = _raw_qr_handler(qrcode_module.handle_qr_code_message)
    result = raw_qr(
        cast(Message, _group_message(text="/qrcode")), cast(TeleBot, bot), 60
    )

    assert result is None
    assert generated == []
    assert bot.sent_photos == []
    _assert_private_chat_notice(bot.sent_messages[-1], reply_to=40)


def test_qr_code_is_refused_while_auto_deletion_is_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    generated = _install_qr_stubs(
        monkeypatch, can_schedule=False, schedule=_unexpected_schedule
    )
    bot = _make_bot()

    raw_qr = _raw_qr_handler(qrcode_module.handle_qr_code_message)
    message = _Msg(from_user=_User(id=11), chat=_Chat(id=1))
    assert raw_qr(cast(Message, message), cast(TeleBot, bot), 60) is None

    assert generated == []
    assert bot.sent_photos == []
    assert bot.sent_messages[-1]["text"] == qrcode_module.QR_DELETION_BUSY_TEXT


@pytest.mark.parametrize(
    "status",
    [
        DeletionStatus.LIMIT_EXCEEDED,
        DeletionStatus.FAILED,
        DeletionStatus.ALREADY_SCHEDULED,
        None,
    ],
    ids=["limit-race", "failed", "unexpected", "error"],
)
def test_qr_code_without_scheduled_deletion_is_removed(
    monkeypatch: pytest.MonkeyPatch, status: DeletionStatus | None
) -> None:
    def _schedule(**kwargs: _PayloadValue) -> DeletionResult:
        del kwargs
        if status is None:
            raise ValueError("delay_seconds must be between 1 and 3600")
        return DeletionResult(
            status=status, message_id=123, user_id=11, pending_count=3
        )

    _install_qr_stubs(monkeypatch, can_schedule=True, schedule=_schedule)
    bot = _make_bot()

    raw_qr = _raw_qr_handler(qrcode_module.handle_qr_code_message)
    message = _Msg(from_user=_User(id=11), chat=_Chat(id=1))
    assert raw_qr(cast(Message, message), cast(TeleBot, bot), 60) is None

    assert len(bot.sent_photos) == 1
    assert bot.deleted == [(1, 123)]
    assert bot.sent_messages[-1]["text"] == qrcode_module.QR_NOT_SCHEDULED_TEXT


def test_qr_code_removal_failure_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_qr_stubs(
        monkeypatch,
        can_schedule=True,
        schedule=lambda **kwargs: DeletionResult(
            status=DeletionStatus.FAILED, message_id=123, user_id=11, pending_count=0
        ),
    )
    bot = _make_bot()

    def _network_error(chat_id: int, message_id: int) -> bool:
        del chat_id, message_id
        raise RuntimeError("network error")

    bot.delete_message = _network_error
    raw_qr = _raw_qr_handler(qrcode_module.handle_qr_code_message)
    message = _Msg(from_user=_User(id=11), chat=_Chat(id=1))
    # The QR code is still in the chat: say so instead of "I removed it".
    assert raw_qr(cast(Message, message), cast(TeleBot, bot), 60) is not None
    assert bot.sent_messages[-1]["text"] == qrcode_module.QR_NOT_REMOVED_TEXT
    assert bot.sent_messages[-1]["reply_to_message_id"] == 123


def test_deletion_manager_can_schedule_reflects_the_pending_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = message_deletion_module.deletion_manager
    pending: defaultdict[int, set[int]] = defaultdict(set, {11: {1, 2}})
    monkeypatch.setattr(manager, "_user_pending_deletions", pending)

    assert manager.can_schedule(11) is True
    pending[11].add(3)
    assert manager.can_schedule(11) is False
    assert manager.can_schedule(12) is True
    # Checking does not create entries for other users.
    assert 12 not in pending
