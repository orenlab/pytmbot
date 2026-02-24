from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import SimpleNamespace
from typing import Literal, cast

import pytest
from telebot import TeleBot
from telebot.handler_backends import CancelUpdate
from telebot.types import Message

import pytmbot.middleware.access_control as access_control_module
import pytmbot.middleware.rate_limit as rate_limit_module


@dataclass
class _BotStub:
    should_fail_send: bool = False
    sent_messages: list[dict[str, object]] = field(default_factory=list)

    def send_message(self, **kwargs: object) -> None:
        if self.should_fail_send:
            raise RuntimeError("send failed")
        self.sent_messages.append(kwargs)


class _NoopThread:
    def __init__(self, **_kwargs: object) -> None:
        return

    def start(self) -> None:
        return


def _build_message(
    *,
    user_id: int,
    text: str,
    chat_id: int = 100,
    username: str = "user",
) -> Message:
    return cast(
        Message,
        SimpleNamespace(
            from_user=SimpleNamespace(id=user_id, username=username, is_bot=False),
            chat=SimpleNamespace(id=chat_id, type="private"),
            message_id=1,
            text=text,
            date=0,
            content_type="text",
        ),
    )


def test_access_control_authorized_user_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = _BotStub()
    monkeypatch.setattr(access_control_module.threading, "Thread", _NoopThread)
    monkeypatch.setattr(
        access_control_module,
        "settings",
        SimpleNamespace(
            access_control=SimpleNamespace(allowed_user_ids=[42]),
            chat_id=SimpleNamespace(global_chat_id=[999]),
        ),
    )

    middleware = access_control_module.AccessControl(cast(TeleBot, bot))
    message = _build_message(user_id=42, text="hello")

    result = middleware.pre_process(message, {})

    assert result is None
    assert bot.sent_messages == []
    assert 42 not in middleware._blocked_until


def test_access_control_unauthorized_attempts_and_blocking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _BotStub()
    monkeypatch.setattr(access_control_module.threading, "Thread", _NoopThread)
    monkeypatch.setattr(
        access_control_module,
        "settings",
        SimpleNamespace(
            access_control=SimpleNamespace(allowed_user_ids=[]),
            chat_id=SimpleNamespace(global_chat_id=[999]),
        ),
    )

    middleware = access_control_module.AccessControl(cast(TeleBot, bot))
    message = _build_message(user_id=10, text="not-allowed")

    first = middleware.pre_process(message, {})
    second = middleware.pre_process(message, {})
    third = middleware.pre_process(message, {})

    assert isinstance(first, CancelUpdate)
    assert isinstance(second, CancelUpdate)
    assert isinstance(third, CancelUpdate)

    # 1st attempt: admin + user warning; 2nd attempt: user warning only
    assert len(bot.sent_messages) == 3
    assert any(msg.get("parse_mode") == "Markdown" for msg in bot.sent_messages)


def test_access_control_setup_command_is_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _BotStub()
    monkeypatch.setattr(access_control_module.threading, "Thread", _NoopThread)
    monkeypatch.setattr(
        access_control_module,
        "settings",
        SimpleNamespace(
            access_control=SimpleNamespace(allowed_user_ids=[]),
            chat_id=SimpleNamespace(global_chat_id=[999]),
        ),
    )

    middleware = access_control_module.AccessControl(cast(TeleBot, bot))
    message = _build_message(user_id=77, text="/getmyid")

    result = middleware.pre_process(message, {})

    assert result is None
    # Setup command still notifies admin once.
    assert len(bot.sent_messages) == 1
    assert bot.sent_messages[0]["chat_id"] == 999


def test_rate_limit_enforces_limit_and_tracks_stats() -> None:
    bot = _BotStub()
    middleware = rate_limit_module.RateLimit(
        cast(TeleBot, bot),
        limit=1,
        period=timedelta(seconds=10),
    )
    message = _build_message(user_id=5, text="ping")

    first = middleware.pre_process(message, {})
    second = middleware.pre_process(message, {})
    stats = middleware.get_stats()

    assert first is None
    assert isinstance(second, CancelUpdate)
    assert len(bot.sent_messages) == 1
    assert stats["total_violations"] >= 1
    assert stats["active_users"] >= 1


def test_rate_limit_cleanup_removes_stale_state() -> None:
    bot = _BotStub()
    middleware = rate_limit_module.RateLimit(
        cast(TeleBot, bot),
        limit=2,
        period=timedelta(seconds=5),
    )
    user_id = 123
    now = datetime.now()
    middleware._user_requests[user_id].append(now - timedelta(minutes=1))
    middleware._violation_count[user_id] = 2
    middleware._last_violation_log[user_id] = now - timedelta(minutes=1)

    middleware._clean_old_requests(user_id, now)

    assert user_id not in middleware._user_requests
    assert user_id not in middleware._violation_count
    assert user_id not in middleware._last_violation_log


def test_access_control_setup_command_with_bot_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _BotStub()
    monkeypatch.setattr(access_control_module.threading, "Thread", _NoopThread)
    monkeypatch.setattr(
        access_control_module,
        "settings",
        SimpleNamespace(
            access_control=SimpleNamespace(allowed_user_ids=[]),
            chat_id=SimpleNamespace(global_chat_id=[999]),
        ),
    )
    middleware = access_control_module.AccessControl(cast(TeleBot, bot))
    message = _build_message(user_id=77, text="/getmyid@dev_pytmbot extra")
    assert middleware._is_setup_command(message) is True


def test_access_control_notify_admin_suppression_and_send_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _BotStub()
    monkeypatch.setattr(access_control_module.threading, "Thread", _NoopThread)
    monkeypatch.setattr(
        access_control_module,
        "settings",
        SimpleNamespace(
            access_control=SimpleNamespace(allowed_user_ids=[]),
            chat_id=SimpleNamespace(global_chat_id=[999]),
        ),
    )
    middleware = access_control_module.AccessControl(cast(TeleBot, bot))

    user_id = 123
    middleware._last_admin_notify[user_id] = datetime.now()
    middleware._notify_admin(
        user_id=user_id,
        username="user",
        chat_id=1,
        attempt=1,
        is_setup_command=False,
    )
    assert bot.sent_messages == []

    bot.should_fail_send = True
    middleware._last_admin_notify.clear()
    middleware._notify_admin(
        user_id=user_id,
        username="user",
        chat_id=1,
        attempt=1,
        is_setup_command=True,
    )
    assert bot.sent_messages == []


def test_access_control_notify_admin_sends_outside_state_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _BotStub()
    monkeypatch.setattr(access_control_module.threading, "Thread", _NoopThread)
    monkeypatch.setattr(
        access_control_module,
        "settings",
        SimpleNamespace(
            access_control=SimpleNamespace(allowed_user_ids=[]),
            chat_id=SimpleNamespace(global_chat_id=[999]),
        ),
    )
    middleware = access_control_module.AccessControl(cast(TeleBot, bot))
    lock_probe = {"was_available": False}

    def _send_message(**kwargs: object) -> None:
        _ = kwargs
        acquired = middleware._state_lock.acquire(blocking=False)
        lock_probe["was_available"] = acquired
        if acquired:
            middleware._state_lock.release()

    monkeypatch.setattr(bot, "send_message", _send_message)
    middleware._notify_admin(
        user_id=111,
        username="tester",
        chat_id=1,
        attempt=1,
        is_setup_command=False,
    )

    assert lock_probe["was_available"] is True


def test_access_control_periodic_cleanup_removes_expired_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _BotStub()
    monkeypatch.setattr(access_control_module.threading, "Thread", _NoopThread)
    monkeypatch.setattr(
        access_control_module,
        "settings",
        SimpleNamespace(
            access_control=SimpleNamespace(allowed_user_ids=[]),
            chat_id=SimpleNamespace(global_chat_id=[999]),
        ),
    )
    middleware = access_control_module.AccessControl(cast(TeleBot, bot))

    expired_user = 5
    active_user = 6
    middleware._blocked_until[expired_user] = datetime.now() - timedelta(seconds=1)
    middleware._blocked_until[active_user] = datetime.now() + timedelta(hours=1)
    middleware._attempt_count[expired_user] = 2
    middleware._last_admin_notify[expired_user] = datetime.now()

    call_count = {"sleep": 0}

    def _sleep(_seconds: float) -> None:
        call_count["sleep"] += 1
        if call_count["sleep"] > 1:
            raise KeyboardInterrupt

    monkeypatch.setattr(access_control_module.time, "sleep", _sleep)

    with pytest.raises(KeyboardInterrupt):
        middleware._periodic_cleanup()

    assert expired_user not in middleware._blocked_until
    assert middleware._attempt_count[expired_user] == 0
    assert expired_user not in middleware._last_admin_notify
    assert active_user in middleware._blocked_until


def test_access_control_periodic_cleanup_masks_expired_ids_in_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _BotStub()
    monkeypatch.setattr(access_control_module.threading, "Thread", _NoopThread)
    monkeypatch.setattr(
        access_control_module,
        "settings",
        SimpleNamespace(
            access_control=SimpleNamespace(allowed_user_ids=[]),
            chat_id=SimpleNamespace(global_chat_id=[999]),
        ),
    )
    middleware = access_control_module.AccessControl(cast(TeleBot, bot))
    expired_user = 7263484885
    middleware._blocked_until[expired_user] = datetime.now() - timedelta(seconds=1)

    captured: list[tuple[str, dict[str, object]]] = []

    class _Logger:
        def __init__(self, ctx: dict[str, object]) -> None:
            self._ctx = ctx

        def info(self, message: str) -> None:
            captured.append((message, self._ctx.copy()))

        def debug(self, message: str) -> None:
            captured.append((message, self._ctx.copy()))

        def error(self, message: str) -> None:
            captured.append((message, self._ctx.copy()))

    class _Ctx:
        def __init__(self, ctx: dict[str, object]) -> None:
            self._ctx = ctx

        def __enter__(self) -> _Logger:
            return _Logger(self._ctx)

        def __exit__(self, *_args: object) -> Literal[False]:
            return False

    monkeypatch.setattr(middleware, "log_context", lambda **kwargs: _Ctx(kwargs))

    call_count = {"sleep": 0}

    def _sleep(_seconds: float) -> None:
        call_count["sleep"] += 1
        if call_count["sleep"] > 1:
            raise KeyboardInterrupt

    monkeypatch.setattr(access_control_module.time, "sleep", _sleep)

    with pytest.raises(KeyboardInterrupt):
        middleware._periodic_cleanup()

    expired_logs = [
        context
        for message, context in captured
        if message == "bot.access.expired.blocks.info"
    ]
    assert expired_logs
    assert expired_logs[0]["expired_user_ids"] == ["726****885"]


def test_access_control_post_process_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _BotStub()
    monkeypatch.setattr(access_control_module.threading, "Thread", _NoopThread)
    monkeypatch.setattr(
        access_control_module,
        "settings",
        SimpleNamespace(
            access_control=SimpleNamespace(allowed_user_ids=[]),
            chat_id=SimpleNamespace(global_chat_id=[999]),
        ),
    )
    middleware = access_control_module.AccessControl(cast(TeleBot, bot))
    message = _build_message(user_id=1, text="hello")

    middleware.post_process(message, {}, None)
    middleware.post_process(message, {}, cast(Exception, CancelUpdate()))
    middleware.post_process(message, {"k": "v"}, RuntimeError("boom"))


def test_rate_limit_send_message_outside_state_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _BotStub()
    middleware = rate_limit_module.RateLimit(
        cast(TeleBot, bot),
        limit=1,
        period=timedelta(seconds=10),
    )
    message = _build_message(user_id=55, text="spam")
    lock_probe = {"was_available": False}

    def _send_message(**kwargs: object) -> None:
        _ = kwargs
        acquired = middleware._state_lock.acquire(blocking=False)
        lock_probe["was_available"] = acquired
        if acquired:
            middleware._state_lock.release()

    monkeypatch.setattr(bot, "send_message", _send_message)
    assert message.from_user is not None
    middleware._handle_rate_limit(message, message.from_user)

    assert lock_probe["was_available"] is True
