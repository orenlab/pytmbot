from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace, TracebackType
from typing import Literal, cast

import pytest
from telebot import TeleBot
from telebot.types import CallbackQuery, Message

import pytmbot.middleware.session_wrapper as session_wrapper_module

type _LogValue = str | int | float | bool | None
type _PayloadValue = (
    str | int | float | bool | None | dict[str, _PayloadValue] | list[_PayloadValue]
)
type _PayloadDict = dict[str, _PayloadValue]


@dataclass
class _LogStub:
    events: list[str]

    def debug(self, message: str, **kwargs: _LogValue) -> None:
        del kwargs
        self.events.append(message)

    def warning(self, message: str, **kwargs: _LogValue) -> None:
        del kwargs
        self.events.append(message)

    def error(self, message: str, **kwargs: _LogValue) -> None:
        del kwargs
        self.events.append(message)

    def success(self, message: str, **kwargs: _LogValue) -> None:
        del kwargs
        self.events.append(message)


@dataclass
class _LogContext:
    events: list[str]

    def __enter__(self) -> _LogStub:
        return _LogStub(self.events)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        del exc_type, exc, tb
        return False


@dataclass
class _AuthComponentStub:
    events: list[str] = field(default_factory=list)

    def log_context(self, **kwargs: _LogValue) -> _LogContext:
        del kwargs
        return _LogContext(self.events)


@dataclass
class _SessionManagerStub:
    authenticated: bool = True
    expired: bool = False
    referer_calls: list[tuple[int, str, str]] = field(default_factory=list)
    state_calls: list[tuple[int, str]] = field(default_factory=list)

    def set_referer_data(self, user_id: int, handler_type: str, referer: str) -> None:
        self.referer_calls.append((user_id, handler_type, referer))

    def set_auth_state(self, user_id: int, state: str) -> None:
        self.state_calls.append((user_id, state))

    def is_authenticated(self, user_id: int) -> bool:
        del user_id
        return self.authenticated

    def is_session_expired(self, user_id: int) -> bool:
        del user_id
        return self.expired


@dataclass
class _UserData:
    id: int
    username: str | None


@dataclass
class _FakeCallback:
    from_user: _UserData | None
    data: str


@dataclass
class _SettingsStub:
    access_control: _AccessControlStub


@dataclass
class _AccessControlStub:
    allowed_user_ids: list[int]
    allowed_admins_ids: list[int]


def _build_message(
    *, user_id: int = 101, username: str = "tester", text: str = "/start"
) -> Message:
    payload: _PayloadDict = {
        "message_id": 1,
        "date": 1,
        "chat": {"id": 10, "type": "private"},
        "from": {
            "id": user_id,
            "is_bot": False,
            "first_name": "Test",
            "username": username,
        },
        "text": text,
    }
    message_from_json = cast(Callable[[_PayloadDict], Message], Message.de_json)
    message_obj = message_from_json(payload)
    if not isinstance(message_obj, Message):
        raise AssertionError("Expected Message instance")
    return message_obj


def test_auth_context_validation_and_message_helpers() -> None:
    with pytest.raises(ValueError):
        session_wrapper_module.AuthContext(
            user_id=0,
            handler_type=session_wrapper_module.HandlerType.MESSAGE,
            referer_handler="/start",
            username="u",
        )

    with pytest.raises(ValueError):
        session_wrapper_module.AuthContext(
            user_id=1,
            handler_type=session_wrapper_module.HandlerType.MESSAGE,
            referer_handler="/start",
            username="x" * (session_wrapper_module.MAX_USERNAME_LENGTH + 1),
        )

    message = _build_message(text="/docker")
    assert session_wrapper_module.is_valid_query(message) is True
    assert session_wrapper_module.get_user_from_query(message) is not None
    assert (
        session_wrapper_module._determine_handler_type(message)
        == session_wrapper_module.HandlerType.MESSAGE
    )
    assert session_wrapper_module._extract_referer_data(message) == "/docker"


def test_callback_helper_branches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_wrapper_module, "CallbackQuery", _FakeCallback)
    callback = _FakeCallback(from_user=_UserData(id=1, username="u"), data="cb:data")

    assert (
        session_wrapper_module._determine_handler_type(cast(CallbackQuery, callback))
        == session_wrapper_module.HandlerType.CALLBACK_QUERY
    )
    assert (
        session_wrapper_module._extract_referer_data(cast(CallbackQuery, callback))
        == "cb:data"
    )


def test_create_auth_context_success_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = _build_message(user_id=222, username="den", text="/help")
    context = session_wrapper_module.create_auth_context(message)
    assert context is not None
    assert context.user_id == 222
    assert context.username == "den"
    assert context.referer_handler == "/help"

    auth_stub = _AuthComponentStub()
    monkeypatch.setattr(session_wrapper_module, "auth_component", auth_stub)
    monkeypatch.setattr(
        session_wrapper_module,
        "get_user_from_query",
        lambda query: (_ for _ in ()).throw(TypeError("boom")),
    )
    assert session_wrapper_module.create_auth_context(message) is None
    assert "bot.session.create.auth.fail" in auth_stub.events


def test_handle_unauthorized_and_access_denied_helpers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = _build_message()
    bot = cast(TeleBot, SimpleNamespace())

    monkeypatch.setattr(session_wrapper_module, "is_valid_query", lambda query: False)
    with pytest.raises(TypeError):
        session_wrapper_module.handle_unauthorized_query(message, bot)
    with pytest.raises(TypeError):
        session_wrapper_module.access_denied_handler(message, bot)

    auth_stub = _AuthComponentStub()
    monkeypatch.setattr(session_wrapper_module, "auth_component", auth_stub)
    monkeypatch.setattr(session_wrapper_module, "is_valid_query", lambda query: True)

    calls: list[str] = []
    monkeypatch.setattr(
        session_wrapper_module,
        "handle_unauthorized_message",
        lambda query, bot: calls.append("unauthorized"),
    )
    monkeypatch.setattr(
        session_wrapper_module,
        "handle_access_denied",
        lambda query, bot: calls.append("denied"),
    )

    session_wrapper_module.handle_unauthorized_query(message, bot)
    session_wrapper_module.access_denied_handler(message, bot)

    assert calls == ["unauthorized", "denied"]
    assert "bot.session.processing.unauthorized.deny" in auth_stub.events
    assert "bot.session.access.denied.deny" in auth_stub.events


def test_unauthenticated_and_expired_helper_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_stub = _SessionManagerStub()
    monkeypatch.setattr(session_wrapper_module, "session_manager", session_stub)

    forwarded: list[str] = []
    monkeypatch.setattr(
        session_wrapper_module,
        "handle_unauthorized_query",
        lambda query, bot: forwarded.append("forwarded"),
    )

    auth_context = session_wrapper_module.AuthContext(
        user_id=77,
        handler_type=session_wrapper_module.HandlerType.MESSAGE,
        referer_handler="/containers",
        username="u77",
    )
    query = _build_message(user_id=77, username="u77", text="/containers")
    bot = cast(TeleBot, SimpleNamespace())

    session_wrapper_module._handle_unauthenticated_user(auth_context, query, bot)
    assert session_stub.referer_calls == [
        (77, session_wrapper_module.HandlerType.MESSAGE.value, "/containers")
    ]

    session_wrapper_module._handle_expired_session(auth_context, query, bot)
    assert session_stub.state_calls == [
        (77, session_wrapper_module.AuthState.UNAUTHENTICATED)
    ]
    assert forwarded == ["forwarded", "forwarded"]


def test_two_factor_auth_required_type_error() -> None:
    def _handler(query: Message, bot: TeleBot) -> str:
        del query, bot
        return "ok"

    wrapped = session_wrapper_module.two_factor_auth_required(_handler)

    with pytest.raises(TypeError):
        wrapped(cast(Message, 0), cast(TeleBot, 0))


def test_two_factor_auth_required_auth_context_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = _build_message()
    bot = cast(TeleBot, SimpleNamespace())

    auth_stub = _AuthComponentStub()
    monkeypatch.setattr(session_wrapper_module, "auth_component", auth_stub)
    monkeypatch.setattr(session_wrapper_module, "is_valid_query", lambda query: True)
    monkeypatch.setattr(
        session_wrapper_module, "create_auth_context", lambda query: None
    )

    denied_calls: list[str] = []
    monkeypatch.setattr(
        session_wrapper_module,
        "access_denied_handler",
        lambda query, bot: denied_calls.append("denied"),
    )

    def _handler(query: Message, bot: TeleBot) -> str:
        del query, bot
        return "ok"

    wrapped = session_wrapper_module.two_factor_auth_required(_handler)
    assert wrapped(message, bot) is None
    assert denied_calls == ["denied"]
    assert "bot.session.create.auth.fail" in auth_stub.events


def test_two_factor_auth_required_not_authorized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message = _build_message(user_id=999, username="x")
    bot = cast(TeleBot, SimpleNamespace())

    auth_stub = _AuthComponentStub()
    monkeypatch.setattr(session_wrapper_module, "auth_component", auth_stub)
    monkeypatch.setattr(session_wrapper_module, "is_valid_query", lambda query: True)
    monkeypatch.setattr(
        session_wrapper_module,
        "create_auth_context",
        lambda query: session_wrapper_module.AuthContext(
            user_id=999,
            handler_type=session_wrapper_module.HandlerType.MESSAGE,
            referer_handler="/x",
            username="x",
        ),
    )
    monkeypatch.setattr(
        session_wrapper_module, "_is_user_authorized", lambda user_id: False
    )

    denied_calls: list[str] = []
    monkeypatch.setattr(
        session_wrapper_module,
        "access_denied_handler",
        lambda query, bot: denied_calls.append("denied"),
    )

    def _handler(query: Message, bot: TeleBot) -> str:
        del query, bot
        return "ok"

    wrapped = session_wrapper_module.two_factor_auth_required(_handler)
    assert wrapped(message, bot) is None
    assert denied_calls == ["denied"]
    assert "bot.session.user.not.warn" in auth_stub.events


@pytest.mark.parametrize(
    ("authenticated", "expired", "forwarded_key", "event_name", "handler_name"),
    [
        (
            False,
            False,
            "unauth",
            "bot.session.authentication.required.warn",
            "_handle_unauthenticated_user",
        ),
        (True, True, "expired", "bot.session.expired.warn", "_handle_expired_session"),
    ],
)
def test_two_factor_auth_required_auth_state_branches(
    monkeypatch: pytest.MonkeyPatch,
    authenticated: bool,
    expired: bool,
    forwarded_key: str,
    event_name: str,
    handler_name: str,
) -> None:
    message = _build_message(user_id=10, username="u10")
    bot = cast(TeleBot, SimpleNamespace())

    auth_stub = _AuthComponentStub()
    session_stub = _SessionManagerStub(authenticated=authenticated, expired=expired)
    monkeypatch.setattr(session_wrapper_module, "auth_component", auth_stub)
    monkeypatch.setattr(session_wrapper_module, "session_manager", session_stub)
    monkeypatch.setattr(session_wrapper_module, "is_valid_query", lambda query: True)
    monkeypatch.setattr(
        session_wrapper_module, "_is_user_authorized", lambda user_id: True
    )
    monkeypatch.setattr(
        session_wrapper_module,
        "create_auth_context",
        lambda query: session_wrapper_module.AuthContext(
            user_id=10,
            handler_type=session_wrapper_module.HandlerType.MESSAGE,
            referer_handler="/y",
            username="u10",
        ),
    )

    forwarded: list[str] = []
    monkeypatch.setattr(
        session_wrapper_module,
        handler_name,
        lambda auth_context, query, bot: forwarded.append(forwarded_key),
    )

    def _handler(query: Message, bot: TeleBot) -> str:
        del query, bot
        return "ok"

    wrapped = session_wrapper_module.two_factor_auth_required(_handler)
    assert wrapped(message, bot) is None
    assert forwarded == [forwarded_key]
    assert event_name in auth_stub.events


def test_two_factor_auth_required_success(monkeypatch: pytest.MonkeyPatch) -> None:
    message = _build_message(user_id=10, username="u10")
    bot = cast(TeleBot, SimpleNamespace())

    auth_stub = _AuthComponentStub()
    session_stub = _SessionManagerStub(authenticated=True, expired=False)
    monkeypatch.setattr(session_wrapper_module, "auth_component", auth_stub)
    monkeypatch.setattr(session_wrapper_module, "session_manager", session_stub)
    monkeypatch.setattr(session_wrapper_module, "is_valid_query", lambda query: True)
    monkeypatch.setattr(
        session_wrapper_module, "_is_user_authorized", lambda user_id: True
    )
    monkeypatch.setattr(
        session_wrapper_module,
        "create_auth_context",
        lambda query: session_wrapper_module.AuthContext(
            user_id=10,
            handler_type=session_wrapper_module.HandlerType.MESSAGE,
            referer_handler="/z",
            username="u10",
        ),
    )

    executed: list[str] = []

    def _handler(query: Message, bot: TeleBot) -> str:
        del query, bot
        executed.append("ok")
        return "result"

    wrapped = session_wrapper_module.two_factor_auth_required(_handler)
    assert wrapped(message, bot) == "result"
    assert executed == ["ok"]
    assert "bot.session.access.granted.ok" in auth_stub.events


def test_is_user_authorized_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        session_wrapper_module,
        "settings",
        _SettingsStub(
            access_control=_AccessControlStub(
                allowed_user_ids=[1, 2],
                allowed_admins_ids=[2],
            )
        ),
    )
    assert session_wrapper_module._is_user_authorized(2) is True
    assert session_wrapper_module._is_user_authorized(1) is False
    assert session_wrapper_module._is_user_authorized(9) is False
