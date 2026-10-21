"""2FA completion, restart barrier, the /start 2fa deep link, and misconfiguration."""

from __future__ import annotations

from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from pathlib import Path
from time import time, time_ns
from types import SimpleNamespace
from typing import cast

import pyotp
import pytest
from telebot import TeleBot
from telebot.types import InlineKeyboardMarkup, Message, ReplyKeyboardMarkup

import pytmbot.handlers.auth_processing.qrcode_processing as qrcode_module
import pytmbot.handlers.auth_processing.twofa_processing as twofa_module
import pytmbot.handlers.bot_handlers.start as start_module
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
_NON_ADMIN = 987654321


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


def _message(
    text: str,
    *,
    username: str | None = None,
    user_id: int = _ADMIN,
    chat_type: str = "private",
) -> Message:
    sender: PayloadDict = {"id": user_id, "is_bot": False, "first_name": "A"}
    if username is not None:
        sender["username"] = username
    chat_id = user_id if chat_type == "private" else -100123
    payload: PayloadDict = {
        "message_id": 1,
        "date": 0,
        "text": text,
        "chat": {"id": chat_id, "type": chat_type},
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
    monkeypatch.setattr(start_module, "session_manager", manager)
    monkeypatch.setattr(
        TwoFactorAuthenticator, "_REPLAY_STATE_FILE", tmp_path / "replay.json"
    )
    monkeypatch.setattr(TwoFactorAuthenticator, "_used_totp_codes", {})
    monkeypatch.setattr(TwoFactorAuthenticator, "_replay_state_loaded", False)
    # The process started long ago: no restart barrier unless a test sets one.
    monkeypatch.setattr(TwoFactorAuthenticator, "_PROCESS_STARTED_AT", 0.0)
    monkeypatch.setattr(TwoFactorAuthenticator, "_replay_floor_step", None)
    monkeypatch.setattr(TwoFactorAuthenticator, "_replay_persist_failed", False)
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


def test_successful_code_resets_failed_attempts(
    session: session_manager_module.SessionManager,
) -> None:
    session.set_auth_state(_ADMIN, session.state_fabric.PROCESSING)
    session.increment_totp_attempts(_ADMIN)
    session.increment_totp_attempts(_ADMIN)
    bot = _Bot()

    _verify(_message(_valid_code("alice"), username="alice"), bot)

    assert session.is_authenticated(_ADMIN) is True
    assert session.get_totp_attempts(_ADMIN) == 0

    # The next 2FA prompt starts clean: one mistake is one attempt, not a block.
    session.set_auth_state(_ADMIN, session.state_fabric.PROCESSING)
    _verify(_message("12345", username="alice"), bot)
    assert session.get_totp_attempts(_ADMIN) == 1
    assert session.get_auth_state(_ADMIN) == session.state_fabric.PROCESSING


def test_code_issued_before_restart_is_not_a_failed_attempt(
    session: session_manager_module.SessionManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The bot just started and its state directory was wiped (tmpfs).
    monkeypatch.setattr(TwoFactorAuthenticator, "_PROCESS_STARTED_AT", time())
    session.set_auth_state(_ADMIN, session.state_fabric.PROCESSING)
    bot = _Bot()

    _verify(_message(_valid_code("alice"), username="alice"), bot)

    assert session.is_authenticated(_ADMIN) is False
    assert session.get_totp_attempts(_ADMIN) == 0
    assert session.get_auth_state(_ADMIN) == session.state_fabric.PROCESSING
    assert bot.payloads("reply_to") == [
        {"text": twofa_module.TOTP_ISSUED_BEFORE_RESTART_TEXT}
    ]


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


def _start(message: Message, bot: _Bot) -> None:
    raw = cast(
        Callable[[Message, TeleBot], None],
        getattr(start_module.handle_start, "__wrapped__", start_module.handle_start),
    )
    raw(message, cast(TeleBot, bot))


@pytest.fixture
def main_menu_texts(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record the normal /start screen instead of building a rich message."""
    texts: list[str] = []

    def _send_rich_main_message(
        bot: object, chat_id: int, html: str, **kwargs: object
    ) -> None:
        del bot, chat_id, kwargs
        texts.append(html)

    monkeypatch.setattr(start_module, "send_rich_main_message", _send_rich_main_message)
    return texts


def test_start_2fa_deep_link_opens_the_2fa_screen_for_an_admin(
    session: session_manager_module.SessionManager, main_menu_texts: list[str]
) -> None:
    # The action pressed in the group is waiting for 2FA.
    session.set_referer_data(_ADMIN, "callback_query", "__manage__:1a2b3c4d5e6f:1")
    bot = _Bot()

    _start(_message("/start 2fa"), bot)

    assert main_menu_texts == []
    screen = bot.payloads("send_message")[-1]
    assert "Two-factor authentication required" in str(screen["text"])
    markup = screen["reply_markup"]
    assert isinstance(markup, ReplyKeyboardMarkup)
    assert "Enter 2FA code" in str(markup.keyboard)
    # The pending action is kept for the "Return" button after 2FA.
    assert session.get_referer_uri(_ADMIN) == "__manage__:1a2b3c4d5e6f:1"


def test_start_2fa_deep_link_when_already_authenticated(
    session: session_manager_module.SessionManager, main_menu_texts: list[str]
) -> None:
    session.set_auth_state(_ADMIN, session.state_fabric.AUTHENTICATED)
    session.set_login_time(_ADMIN)
    bot = _Bot()

    _start(_message("/start 2fa"), bot)

    assert main_menu_texts == []
    reply = bot.payloads("send_message")[-1]
    assert reply["text"] == start_module.TWOFA_ALREADY_CONFIRMED_TEXT
    assert isinstance(reply["reply_markup"], ReplyKeyboardMarkup)


@pytest.mark.parametrize(
    ("text", "user_id", "chat_type"),
    [
        ("/start 2fa", _NON_ADMIN, "private"),
        ("/start 2fa", _ADMIN, "supergroup"),
        ("/start other", _ADMIN, "private"),
        ("/start", _ADMIN, "private"),
    ],
    ids=["non-admin", "group", "other-payload", "no-payload"],
)
def test_start_shows_the_main_menu_otherwise(
    session: session_manager_module.SessionManager,
    main_menu_texts: list[str],
    text: str,
    user_id: int,
    chat_type: str,
) -> None:
    del session
    bot = _Bot()

    _start(_message(text, user_id=user_id, chat_type=chat_type), bot)

    assert len(main_menu_texts) == 1
    assert bot.payloads("send_message") == []
