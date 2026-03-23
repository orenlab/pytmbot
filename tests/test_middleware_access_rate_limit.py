from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import SimpleNamespace, TracebackType
from typing import Literal, cast

import pytest
from telebot import TeleBot
from telebot.handler_backends import CancelUpdate
from telebot.types import Message

import pytmbot.middleware.access_control as access_control_module
import pytmbot.middleware.rate_limit as rate_limit_module

type _PayloadScalar = str | int | float | bool | None
type _PayloadValue = _PayloadScalar | list["_PayloadValue"] | dict[str, "_PayloadValue"]
type _PayloadDict = dict[str, _PayloadValue]


@dataclass
class _BotStub:
    should_fail_send: bool = False
    sent_messages: list[_PayloadDict] = field(default_factory=list)
    answered_callbacks: list[_PayloadDict] = field(default_factory=list)

    def send_message(self, **kwargs: _PayloadValue) -> None:
        if self.should_fail_send:
            raise RuntimeError("send failed")
        self.sent_messages.append(dict(kwargs))

    def answer_callback_query(
        self, *args: _PayloadValue, **kwargs: _PayloadValue
    ) -> None:
        if self.should_fail_send:
            raise RuntimeError("send failed")
        self.answered_callbacks.append(
            {
                "args": list(args),
                "kwargs": dict(kwargs),
            }
        )


@dataclass
class _CapturedLogger:
    context: _PayloadDict
    sink: list[tuple[str, _PayloadDict]]

    def info(self, message: str) -> None:
        self.sink.append((message, self.context.copy()))

    def debug(self, message: str) -> None:
        self.sink.append((message, self.context.copy()))

    def error(self, message: str) -> None:
        self.sink.append((message, self.context.copy()))


@dataclass
class _CapturedContext:
    context: _PayloadDict
    sink: list[tuple[str, _PayloadDict]]

    def __enter__(self) -> _CapturedLogger:
        return _CapturedLogger(self.context, self.sink)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> Literal[False]:
        del exc_type, exc, tb
        return False


class _NoopThread:
    def __init__(self, **_kwargs: _PayloadValue) -> None:
        return

    def start(self) -> None:
        return


def _build_message(
    *,
    user_id: int,
    text: str,
    chat_id: int = 100,
    username: str | None = "user",
    first_name: str | None = None,
    last_name: str | None = None,
) -> Message:
    return cast(
        Message,
        SimpleNamespace(
            from_user=SimpleNamespace(
                id=user_id,
                username=username,
                first_name=first_name,
                last_name=last_name,
                is_bot=False,
            ),
            chat=SimpleNamespace(id=chat_id, type="private"),
            message_id=1,
            text=text,
            date=0,
            content_type="text",
        ),
    )


def _build_callback(
    *,
    user_id: int,
    data: str,
    chat_id: int = 100,
    callback_id: str = "cb-1",
) -> Message:
    callback = SimpleNamespace(
        id=callback_id,
        data=data,
        from_user=SimpleNamespace(
            id=user_id,
            username="user",
            first_name=None,
            last_name=None,
            is_bot=False,
        ),
        message=SimpleNamespace(
            chat=SimpleNamespace(id=chat_id, type="private"),
            message_id=1,
            date=0,
            content_type="text",
        ),
    )
    return cast(Message, callback)


def _build_access_control_middleware(
    monkeypatch: pytest.MonkeyPatch,
    bot: _BotStub,
    *,
    allowed_user_ids: list[int] | None = None,
    admin_chat_id: int = 999,
) -> access_control_module.AccessControl:
    monkeypatch.setattr(
        "pytmbot.middleware.access_control.threading.Thread",
        _NoopThread,
    )
    monkeypatch.setattr(
        access_control_module,
        "settings",
        SimpleNamespace(
            access_control=SimpleNamespace(allowed_user_ids=allowed_user_ids or []),
            chat_id=SimpleNamespace(global_chat_id=[admin_chat_id]),
        ),
    )
    return access_control_module.AccessControl(cast(TeleBot, bot))


def _install_log_capture(
    monkeypatch: pytest.MonkeyPatch,
    middleware: access_control_module.AccessControl,
) -> list[tuple[str, _PayloadDict]]:
    captured: list[tuple[str, _PayloadDict]] = []
    monkeypatch.setattr(
        middleware,
        "log_context",
        lambda **kwargs: _CapturedContext(cast(_PayloadDict, kwargs), captured),
    )
    return captured


def test_access_control_authorized_user_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = _BotStub()
    middleware = _build_access_control_middleware(
        monkeypatch,
        bot,
        allowed_user_ids=[42],
    )
    message = _build_message(user_id=42, text="hello")

    result = middleware.pre_process(message, {})

    assert result is None
    assert bot.sent_messages == []
    assert 42 not in middleware._blocked_until


def test_access_control_unauthorized_attempts_and_blocking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _BotStub()
    middleware = _build_access_control_middleware(monkeypatch, bot)
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
    middleware = _build_access_control_middleware(monkeypatch, bot)
    message = _build_message(user_id=77, text="/getmyid")

    result = middleware.pre_process(message, {})

    assert result is None
    # Setup command still notifies admin once.
    assert len(bot.sent_messages) == 1
    assert bot.sent_messages[0]["chat_id"] == 999


def test_access_control_callback_query_is_checked_and_denied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _BotStub()
    middleware = _build_access_control_middleware(monkeypatch, bot)
    callback = _build_callback(user_id=88, data="d:containers")

    result = middleware.pre_process(callback, {})

    assert isinstance(result, CancelUpdate)
    assert len(bot.answered_callbacks) == 1
    callback_kwargs = cast(
        dict[str, _PayloadValue], bot.answered_callbacks[0]["kwargs"]
    )
    assert callback_kwargs["show_alert"] is True


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


def test_rate_limit_handles_callback_query_updates() -> None:
    bot = _BotStub()
    middleware = rate_limit_module.RateLimit(
        cast(TeleBot, bot),
        limit=1,
        period=timedelta(seconds=10),
    )
    callback = _build_callback(user_id=5, data="cb:ping")

    first = middleware.pre_process(callback, {})
    second = middleware.pre_process(callback, {})

    assert first is None
    assert isinstance(second, CancelUpdate)
    assert not bot.sent_messages
    assert len(bot.answered_callbacks) == 1


def test_access_control_setup_command_with_bot_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _BotStub()
    monkeypatch.setattr(
        "pytmbot.middleware.access_control.threading.Thread", _NoopThread
    )
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
    monkeypatch.setattr(
        "pytmbot.middleware.access_control.threading.Thread", _NoopThread
    )
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
    monkeypatch.setattr(
        "pytmbot.middleware.access_control.threading.Thread", _NoopThread
    )
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

    def _send_message(**kwargs: _PayloadValue) -> None:
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


def test_access_control_admin_notification_uses_name_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _BotStub()
    middleware = _build_access_control_middleware(monkeypatch, bot)
    message = _build_message(
        user_id=777,
        text="not-allowed",
        username=None,
        first_name="Firstname",
        last_name="Tester",
    )

    result = middleware.pre_process(message, {})

    assert isinstance(result, CancelUpdate)
    assert len(bot.sent_messages) == 2  # admin + user warning
    admin_text = cast(str, bot.sent_messages[0]["text"])
    assert "un***wn" not in admin_text
    assert "Fir" in admin_text or "Tes" in admin_text


def test_access_control_admin_notification_masks_admin_chat_id_in_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _BotStub()
    middleware = _build_access_control_middleware(
        monkeypatch, bot, admin_chat_id=-4970000716
    )
    captured = _install_log_capture(monkeypatch, middleware)

    middleware._notify_admin(
        user_id=123456789,
        username="unknown_user",
        chat_id=5334652113,
        attempt=1,
        is_setup_command=False,
    )

    info_logs = [
        context
        for message, context in captured
        if message == "bot.access.admin.notification.info"
    ]
    assert info_logs
    assert info_logs[0]["admin_chat_id"] == "-497****716"


def test_access_control_periodic_cleanup_removes_expired_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _BotStub()
    middleware = _build_access_control_middleware(monkeypatch, bot)

    expired_user = 5
    active_user = 6
    middleware._blocked_until[expired_user] = datetime.now() - timedelta(seconds=1)
    middleware._blocked_until[active_user] = datetime.now() + timedelta(hours=1)
    middleware._attempt_count[expired_user] = 2
    middleware._last_admin_notify[expired_user] = datetime.now()

    call_count = {"wait": 0}

    def _wait() -> bool:
        call_count["wait"] += 1
        if call_count["wait"] > 1:
            raise KeyboardInterrupt
        return False

    monkeypatch.setattr(middleware, "_wait_for_cleanup_interval", _wait)

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
    middleware = _build_access_control_middleware(monkeypatch, bot)
    expired_user = 7263484885
    middleware._blocked_until[expired_user] = datetime.now() - timedelta(seconds=1)

    captured = _install_log_capture(monkeypatch, middleware)

    call_count = {"wait": 0}

    def _wait() -> bool:
        call_count["wait"] += 1
        if call_count["wait"] > 1:
            raise KeyboardInterrupt
        return False

    monkeypatch.setattr(middleware, "_wait_for_cleanup_interval", _wait)

    with pytest.raises(KeyboardInterrupt):
        middleware._periodic_cleanup()

    expired_logs = [
        context
        for message, context in captured
        if message == "bot.access.expired.blocks.info"
    ]
    assert expired_logs
    assert expired_logs[0]["expired_user_ids"] == ["72******85"]


def test_access_control_post_process_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _BotStub()
    monkeypatch.setattr(
        "pytmbot.middleware.access_control.threading.Thread", _NoopThread
    )
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

    def _send_message(**kwargs: _PayloadValue) -> None:
        _ = kwargs
        acquired = middleware._state_lock.acquire(blocking=False)
        lock_probe["was_available"] = acquired
        if acquired:
            middleware._state_lock.release()

    monkeypatch.setattr(bot, "send_message", _send_message)
    assert message.from_user is not None
    middleware._handle_rate_limit(message, message.from_user)

    assert lock_probe["was_available"] is True
