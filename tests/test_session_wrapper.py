from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace, TracebackType
from typing import Literal, cast

import pytest
from telebot import TeleBot
from telebot.types import CallbackQuery, Message

import pytmbot.middleware.session_wrapper as session_wrapper_module
from tests._telebot_objects import telegram_object_from_payload

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


def _make_session_manager_stub(
    *, authenticated: bool = True, expired: bool = False
) -> SimpleNamespace:
    referer_calls: list[tuple[int, str, str]] = []
    state_calls: list[tuple[int, str]] = []

    def set_referer_data(user_id: int, handler_type: str, referer: str) -> None:
        referer_calls.append((user_id, handler_type, referer))

    def set_auth_state(user_id: int, state: str) -> None:
        state_calls.append((user_id, state))

    def is_authenticated(user_id: int) -> bool:
        del user_id
        return authenticated

    def is_session_expired(user_id: int) -> bool:
        del user_id
        return expired

    return SimpleNamespace(
        authenticated=authenticated,
        expired=expired,
        referer_calls=referer_calls,
        state_calls=state_calls,
        set_referer_data=set_referer_data,
        set_auth_state=set_auth_state,
        is_authenticated=is_authenticated,
        is_session_expired=is_session_expired,
    )


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
    return telegram_object_from_payload(
        payload,
        parser=cast(Callable[[_PayloadDict], Message], Message.de_json),
        expected_type=Message,
    )


def _build_auth_context(
    *, user_id: int, username: str, referer_handler: str
) -> session_wrapper_module.AuthContext:
    return session_wrapper_module.AuthContext(
        user_id=user_id,
        handler_type=session_wrapper_module.HandlerType.MESSAGE,
        referer_handler=referer_handler,
        username=username,
    )


def _configure_two_factor_test(
    monkeypatch: pytest.MonkeyPatch,
    *,
    user_id: int,
    username: str,
    referer_handler: str,
    authenticated: bool = True,
    expired: bool = False,
    user_authorized: bool = True,
    auth_context: session_wrapper_module.AuthContext | None = None,
) -> tuple[Message, TeleBot, _AuthComponentStub, SimpleNamespace]:
    message = _build_message(user_id=user_id, username=username)
    bot = cast(TeleBot, SimpleNamespace())
    auth_stub = _AuthComponentStub()
    session_stub = _make_session_manager_stub(
        authenticated=authenticated, expired=expired
    )
    monkeypatch.setattr(session_wrapper_module, "auth_component", auth_stub)
    monkeypatch.setattr(session_wrapper_module, "session_manager", session_stub)
    monkeypatch.setattr(session_wrapper_module, "is_valid_query", lambda query: True)
    monkeypatch.setattr(
        session_wrapper_module,
        "_is_user_authorized",
        lambda current_user_id: user_authorized,
    )
    monkeypatch.setattr(
        session_wrapper_module,
        "create_auth_context",
        lambda query: (
            auth_context
            if auth_context is not None
            else _build_auth_context(
                user_id=user_id,
                username=username,
                referer_handler=referer_handler,
            )
        ),
    )
    return message, bot, auth_stub, session_stub


def _wrap_message_handler(
    executed: list[str] | None = None,
    *,
    return_value: str = "ok",
) -> Callable[[Message, TeleBot], str]:
    def _handler(query: Message, bot: TeleBot) -> str:
        del query, bot
        if executed is not None:
            executed.append(return_value)
        return return_value

    return _handler


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
    message, bot, auth_stub, _ = _configure_two_factor_test(
        monkeypatch,
        user_id=101,
        username="tester",
        referer_handler="/start",
        auth_context=None,
    )
    monkeypatch.setattr(
        session_wrapper_module, "create_auth_context", lambda query: None
    )

    denied_calls: list[str] = []
    monkeypatch.setattr(
        session_wrapper_module,
        "access_denied_handler",
        lambda query, bot: denied_calls.append("denied"),
    )

    wrapped = session_wrapper_module.two_factor_auth_required(_wrap_message_handler())
    assert wrapped(message, bot) is None
    assert denied_calls == ["denied"]
    assert "bot.session.create.auth.fail" in auth_stub.events


def test_two_factor_auth_required_not_authorized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    message, bot, auth_stub, _ = _configure_two_factor_test(
        monkeypatch,
        user_id=999,
        username="x",
        referer_handler="/x",
        user_authorized=False,
    )

    denied_calls: list[str] = []
    monkeypatch.setattr(
        session_wrapper_module,
        "access_denied_handler",
        lambda query, bot: denied_calls.append("denied"),
    )

    wrapped = session_wrapper_module.two_factor_auth_required(_wrap_message_handler())
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
        )
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
    message, bot, auth_stub, _ = _configure_two_factor_test(
        monkeypatch,
        user_id=10,
        username="u10",
        referer_handler="/y",
        authenticated=authenticated,
        expired=expired,
    )

    forwarded: list[str] = []
    monkeypatch.setattr(
        session_wrapper_module,
        handler_name,
        lambda auth_context, query, bot: forwarded.append(forwarded_key),
    )

    wrapped = session_wrapper_module.two_factor_auth_required(_wrap_message_handler())
    assert wrapped(message, bot) is None
    assert forwarded == [forwarded_key]
    assert event_name in auth_stub.events


def test_two_factor_auth_required_success(monkeypatch: pytest.MonkeyPatch) -> None:
    message, bot, auth_stub, _ = _configure_two_factor_test(
        monkeypatch,
        user_id=10,
        username="u10",
        referer_handler="/z",
    )

    executed: list[str] = []
    wrapped = session_wrapper_module.two_factor_auth_required(
        _wrap_message_handler(executed, return_value="result")
    )
    assert wrapped(message, bot) == "result"
    assert executed == ["result"]
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
