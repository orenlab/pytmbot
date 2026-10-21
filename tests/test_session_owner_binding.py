"""2FA gate vs. button ownership in group chats (owner check runs first)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import cast

import pytest
from telebot import TeleBot
from telebot.types import CallbackQuery

import pytmbot.middleware.session_wrapper as session_wrapper_module
from tests._telebot_objects import PayloadDict, telegram_object_from_payload

_ADMIN_A = 123456789  # allowed admin in pytmbot.yaml.sample
_USER_B = 987654321  # allowed, not an admin
_GROUP_CHAT = -100555
_CONTAINER_ID = "1a2b3c4d5e6f"


def _make_call(
    data: str,
    *,
    presser: int,
    chat_id: int = _GROUP_CHAT,
    chat_type: str = "supergroup",
) -> CallbackQuery:
    payload: PayloadDict = {
        "id": "cbq-1",
        "from": {"id": presser, "is_bot": False, "first_name": f"U{presser}"},
        "chat_instance": "ci",
        "data": data,
        "message": {
            "message_id": 4242,
            "date": 0,
            "chat": {"id": chat_id, "type": chat_type, "title": "ops"},
            "from": {"id": 1111, "is_bot": True, "first_name": "bot"},
            "text": "container details",
        },
    }
    return telegram_object_from_payload(
        payload,
        parser=cast(Callable[[PayloadDict], CallbackQuery], CallbackQuery.de_json),
        expected_type=CallbackQuery,
    )


@dataclass
class _Bot:
    answers: list[dict[str, object]] = field(default_factory=list)
    deleted: list[tuple[int, int]] = field(default_factory=list)
    sent: list[dict[str, object]] = field(default_factory=list)

    def answer_callback_query(
        self, callback_query_id: str, text: str | None = None, **kwargs: object
    ) -> bool:
        self.answers.append({"id": callback_query_id, "text": text, **kwargs})
        return True

    def delete_message(self, chat_id: int, message_id: int) -> bool:
        self.deleted.append((chat_id, message_id))
        return True

    def send_message(self, **kwargs: object) -> SimpleNamespace:
        self.sent.append(dict(kwargs))
        return SimpleNamespace(message_id=1)


@dataclass
class _Session:
    authenticated: set[int] = field(default_factory=set)
    referers: dict[int, tuple[str, str]] = field(default_factory=dict)

    def is_authenticated(self, user_id: int) -> bool:
        return user_id in self.authenticated

    def set_referer_data(self, user_id: int, handler_type: str, referer: str) -> None:
        self.referers[user_id] = (handler_type, referer)


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> _Session:
    fake = _Session()
    monkeypatch.setattr(session_wrapper_module, "session_manager", fake)
    return fake


def _run(call: CallbackQuery, bot: _Bot) -> list[str]:
    executed: list[str] = []

    def handler(query: CallbackQuery, telebot: TeleBot) -> None:
        del telebot
        executed.append(str(query.data))

    wrapped = session_wrapper_module.two_factor_auth_required(handler)
    wrapped(call, cast(TeleBot, bot))
    return executed


@pytest.mark.parametrize(
    ("data", "presser", "authenticated"),
    [
        (f"__manage__:{_CONTAINER_ID}:{_ADMIN_A}", _USER_B, False),
        (f"__stop__:{_CONTAINER_ID}:{_ADMIN_A}", _USER_B, False),
        (f"__get_logs__:nav:0123456789ab:1:{_ADMIN_A}", _USER_B, False),
        # Even an authenticated admin cannot use another user's button.
        (f"__restart__:{_CONTAINER_ID}:{_USER_B}", _ADMIN_A, True),
        (f"__restart__:{_CONTAINER_ID}:{_USER_B}", _ADMIN_A, False),
    ],
)
def test_foreign_button_is_rejected_before_admin_and_2fa_checks(
    session: _Session, data: str, presser: int, authenticated: bool
) -> None:
    if authenticated:
        session.authenticated.add(presser)
    bot = _Bot()

    executed = _run(_make_call(data, presser=presser), bot)

    assert executed == []
    assert bot.deleted == []
    assert bot.sent == []
    assert session.referers == {}
    assert bot.answers == [
        {
            "id": "cbq-1",
            "text": "This button belongs to another user.",
            "show_alert": True,
        }
    ]


def test_owner_without_session_gets_2fa_prompt_and_manage_return_target(
    session: _Session,
) -> None:
    bot = _Bot()
    data = f"__stop_confirm__:{_CONTAINER_ID}:{_ADMIN_A}"

    executed = _run(_make_call(data, presser=_ADMIN_A), bot)

    assert executed == []
    # In a group the pressed message stays; 2FA continues in the private chat.
    assert bot.deleted == []
    assert bot.sent and bot.sent[0]["chat_id"] == _GROUP_CHAT
    assert "private chat" in str(bot.sent[0]["text"])
    # A state-changing action is never stored as the post-2FA return target.
    assert session.referers[_ADMIN_A] == (
        "callback_query",
        f"__manage__:{_CONTAINER_ID}:{_ADMIN_A}",
    )


def test_unbound_button_in_group_is_never_deleted(session: _Session) -> None:
    bot = _Bot()
    _run(_make_call("back_to_containers", presser=_ADMIN_A), bot)
    assert bot.deleted == []
    assert bot.sent  # the private-chat notice is still sent
    assert session.referers[_ADMIN_A] == ("callback_query", "back_to_containers")


def test_non_admin_owner_is_denied_on_their_own_message(session: _Session) -> None:
    bot = _Bot()
    data = f"__manage__:{_CONTAINER_ID}:{_USER_B}"
    executed = _run(_make_call(data, presser=_USER_B), bot)
    assert executed == []
    assert bot.deleted == [(_GROUP_CHAT, 4242)]
    assert session.referers == {}


def test_authenticated_owner_runs_handler(session: _Session) -> None:
    session.authenticated.add(_ADMIN_A)
    bot = _Bot()
    data = f"__manage__:{_CONTAINER_ID}:{_ADMIN_A}"
    assert _run(_make_call(data, presser=_ADMIN_A), bot) == [data]
    assert bot.answers == []
    assert bot.deleted == []
