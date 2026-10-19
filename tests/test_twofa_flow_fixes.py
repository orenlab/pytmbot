"""2FA completion without a pending action, without a username, and on misconfiguration."""

from __future__ import annotations

from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from pathlib import Path
from time import time_ns
from types import SimpleNamespace
from typing import cast

import pyotp
import pytest
from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, Message, ReplyKeyboardMarkup

import pytmbot.handlers.auth_processing.qrcode_processing as qrcode_module
import pytmbot.handlers.auth_processing.twofa_processing as twofa_module
import pytmbot.middleware.session_manager as session_manager_module
import pytmbot.utils.totp as totp_module
from pytmbot.utils.message_deletion import (
    DeletionResult,
    DeletionStatus,
    deletion_manager,
)
from pytmbot.utils.totp import TwoFactorAuthenticator
from tests._telebot_objects import PayloadDict, telegram_object_from_payload

_ADMIN = 123456789


@dataclass
class _Bot:
    """Records every Bot API call as (method, payload)."""

    calls: list[tuple[str, dict[str, object]]] = field(default_factory=list)

    def _record(self, method: str, **payload: object) -> SimpleNamespace:
        self.calls.append((method, payload))
        return SimpleNamespace(message_id=len(self.calls))

    def reply_to(self, message: Message, text: str, **kwargs: object) -> None:
        del message
        self._record("reply_to", text=text, **kwargs)

    def send_chat_action(self, chat_id: int, action: str) -> bool:
        self._record("send_chat_action", chat_id=chat_id, action=action)
        return True

    def send_message(self, **kwargs: object) -> SimpleNamespace:
        return self._record("send_message", **kwargs)

    def send_photo(self, chat_id: int, **kwargs: object) -> SimpleNamespace:
        return self._record("send_photo", chat_id=chat_id, **kwargs)

    def payloads(self, method: str) -> list[dict[str, object]]:
        return [payload for name, payload in self.calls if name == method]


def _message(text: str, *, username: str | None = None) -> Message:
    sender: PayloadDict = {"id": _ADMIN, "is_bot": False, "first_name": "A"}
    if username is not None:
        sender["username"] = username
    payload: PayloadDict = {
        "message_id": 1,
        "date": 0,
        "text": text,
        "chat": {"id": _ADMIN, "type": "private"},
        "from": sender,
    }
    return telegram_object_from_payload(
        payload,
        parser=cast(Callable[[PayloadDict], Message], Message.de_json),
        expected_type=Message,
    )


@pytest.fixture
def session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Generator[session_manager_module.SessionManager, None, None]:
    monkeypatch.setattr(
        session_manager_module.SessionManager,
        "_start_cleanup_thread",
        lambda self: None,
    )
    manager = session_manager_module.SessionManager(f"twofa-test-{time_ns()}")
    monkeypatch.setattr(twofa_module, "session_manager", manager)
    monkeypatch.setattr(
        TwoFactorAuthenticator, "_REPLAY_STATE_FILE", tmp_path / "replay.json"
    )
    monkeypatch.setattr(TwoFactorAuthenticator, "_used_totp_codes", {})
    monkeypatch.setattr(TwoFactorAuthenticator, "_replay_state_loaded", False)
    monkeypatch.setattr(twofa_module, "_totp_attempt_times", {})
    yield manager
    manager.shutdown()


def _valid_code(username: str | None) -> str:
    secret = TwoFactorAuthenticator(_ADMIN, username)._generate_secret()
    return pyotp.TOTP(secret).now()


def _verify(message: Message, bot: _Bot) -> None:
    raw = cast(
        Callable[[Message, TeleBot], None],
        getattr(
            twofa_module.handle_totp_code_verification,
            "__wrapped__",
            twofa_module.handle_totp_code_verification,
        ),
    )
    raw(message, cast(TeleBot, bot))


def test_correct_code_without_pending_action_confirms_with_main_menu(
    session: session_manager_module.SessionManager,
) -> None:
    session.set_auth_state(_ADMIN, session.state_fabric.PROCESSING)
    bot = _Bot()

    _verify(_message(_valid_code("alice"), username="alice"), bot)

    assert session.is_authenticated(_ADMIN) is True
    assert len(bot.payloads("reply_to")) == 1
    assert isinstance(bot.payloads("reply_to")[0]["reply_markup"], ReplyKeyboardMarkup)


def test_admin_without_username_can_complete_2fa(
    session: session_manager_module.SessionManager,
) -> None:
    session.set_auth_state(_ADMIN, session.state_fabric.PROCESSING)
    session.set_referer_data(_ADMIN, "callback_query", "__stop__:1a2b3c4d5e6f:1")
    bot = _Bot()

    _verify(_message(_valid_code(None)), bot)

    assert session.is_authenticated(_ADMIN) is True
    markup = bot.payloads("reply_to")[0]["reply_markup"]
    assert isinstance(markup, InlineKeyboardMarkup)
    button = markup.keyboard[0][0]
    assert button.callback_data == "__manage__:1a2b3c4d5e6f:1"
    assert button.text == "🦈 Return to container actions"


def test_totp_configuration_error_is_reported_to_the_user(
    session: session_manager_module.SessionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session.set_auth_state(_ADMIN, session.state_fabric.PROCESSING)
    monkeypatch.setattr(totp_module, "_build_secret_key_material", lambda: "")
    bot = _Bot()

    _verify(_message("123456"), bot)

    assert session.is_authenticated(_ADMIN) is False
    assert bot.payloads("reply_to") == [{"text": twofa_module.TOTP_UNAVAILABLE_TEXT}]


def _qr(message: Message, bot: _Bot) -> Message | None:
    raw = cast(
        Callable[[Message, TeleBot, int], Message | None],
        getattr(
            qrcode_module.handle_qr_code_message,
            "__wrapped__",
            qrcode_module.handle_qr_code_message,
        ),
    )
    return raw(message, cast(TeleBot, bot), 60)


def test_qr_code_for_user_without_username(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        deletion_manager,
        "schedule_deletion",
        lambda **kwargs: DeletionResult(
            status=DeletionStatus.SCHEDULED,
            message_id=6,
            user_id=_ADMIN,
            pending_count=1,
        ),
    )
    bot = _Bot()
    assert _qr(_message("/qrcode"), bot) is not None
    assert bot.payloads("send_photo") and str(
        bot.payloads("send_photo")[0]["photo"]
    ).startswith("b'\\x89PNG")


def test_qr_code_configuration_error_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(totp_module, "_build_secret_key_material", lambda: "")
    bot = _Bot()
    assert _qr(_message("/qrcode", username="alice"), bot) is None
    assert bot.payloads("send_photo") == []
    assert bot.payloads("send_message")[-1]["text"] == qrcode_module.QR_UNAVAILABLE_TEXT
