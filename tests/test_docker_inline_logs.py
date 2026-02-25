from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import cast

import pytest
from telebot import TeleBot
from telebot.types import CallbackQuery

import pytmbot.handlers.docker_handlers.inline.logs as logs_module
import pytmbot.handlers.server_handlers.inline.common as inline_common_module
from pytmbot.exceptions import ContainerLogsUnavailableError, ErrorContext
from pytmbot.handlers.docker_handlers.inline.logs import (
    LOGS_ACTION_FILE,
    LOGS_ACTION_NAV,
    LOGS_ACTION_OPEN,
    LOGS_ACTION_REFRESH,
    LOGS_CALLBACK_PREFIX,
    LOGS_EMPTY_MESSAGE,
    LOGS_FILE_AUTO_DELETE_DELAY_SECONDS,
    LOGS_FILE_DELETION_NOTICE,
    LOGS_TRUNCATION_NOTICE,
    LogsSession,
    LogsSessionStore,
    ParsedLogsCallback,
)
from pytmbot.utils.message_deletion import DeletionResult, DeletionStatus

_NOT_MODIFIED_DESCRIPTION = (
    "Bad Request: message is not modified: specified new message content and reply "
    "markup are exactly the same as a current content and reply markup of the message"
)


@dataclass
class _DummyChat:
    id: int = 111


@dataclass
class _DummyMessage:
    chat: _DummyChat = field(default_factory=_DummyChat)
    message_id: int = 222


@dataclass
class _DummyUser:
    id: int = 333


@dataclass
class _DummyCall:
    id: str = "cb-id"
    data: str | None = None
    from_user: _DummyUser | None = field(default_factory=_DummyUser)
    message: _DummyMessage | None = field(default_factory=_DummyMessage)


@dataclass
class _SentDocument:
    message_id: int = 987


@dataclass
class _DummyBot:
    token: str = "12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE"
    edited: list[dict[str, object]] = field(default_factory=list)
    documents: list[dict[str, object]] = field(default_factory=list)
    messages: list[dict[str, object]] = field(default_factory=list)
    callback_answers: list[dict[str, object]] = field(default_factory=list)

    def edit_message_text(self, **kwargs: object) -> str:
        self.edited.append(kwargs)
        return "edited"

    def send_document(self, **kwargs: object) -> _SentDocument:
        self.documents.append(kwargs)
        return _SentDocument()

    def send_message(self, chat_id: int, text: str, **kwargs: object) -> str:
        payload: dict[str, object] = {"chat_id": chat_id, "text": text, **kwargs}
        self.messages.append(payload)
        return "message-sent"

    def answer_callback_query(self, **kwargs: object) -> str:
        self.callback_answers.append(kwargs)
        return "callback-answered"


def _make_session(
    *,
    session_id: str = "sess-1",
    container_name: str = "container",
    user_id: int = 333,
    raw_logs: str = "line1\nline2",
    chunks: list[str] | None = None,
) -> LogsSession:
    return LogsSession(
        session_id=session_id,
        container_name=container_name,
        user_id=user_id,
        raw_logs=raw_logs,
        chunks=chunks if chunks is not None else ["line1", "line2"],
        created_at=100.0,
    )


def _raw_handle_get_logs() -> Callable[[CallbackQuery, TeleBot], None]:
    first_layer = getattr(
        logs_module.handle_get_logs, "__wrapped__", logs_module.handle_get_logs
    )
    second_layer = getattr(first_layer, "__wrapped__", first_layer)
    return cast(Callable[[CallbackQuery, TeleBot], None], second_layer)


def _allow_logs_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        logs_module,
        "authorize_docker_callback_request",
        lambda call, called_user_id: (True, ""),
    )
    monkeypatch.setattr(
        logs_module,
        "_validate_logs_session_access",
        lambda **kwargs: True,
    )


def test_logs_session_store_create_get_and_expire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LogsSessionStore(ttl_seconds=5)
    monkeypatch.setattr(logs_module.time, "time", lambda: 10.0)
    monkeypatch.setattr(logs_module.time, "time_ns", lambda: 99)

    created = store.create("web", 1, "logs", ["logs"])
    loaded = store.get(created.session_id)
    assert loaded is not None
    assert loaded.session_id == created.session_id

    monkeypatch.setattr(logs_module.time, "time", lambda: 20.0)
    assert store.get(created.session_id) is None


def test_logs_session_store_create_handles_id_collision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = LogsSessionStore(ttl_seconds=10)
    store._sessions["dup"] = _make_session(session_id="dup")

    generated = iter(["dup", "new-id"])
    monkeypatch.setattr(
        LogsSessionStore,
        "_generate_session_id",
        staticmethod(lambda _container, _user: next(generated)),
    )
    monkeypatch.setattr(logs_module.time, "time", lambda: 1.0)

    session = store.create("web", 1, "abc", ["abc"])
    assert session.session_id == "new-id"


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        (
            "__get_logs__:nginx:100",
            ParsedLogsCallback(
                action=LOGS_ACTION_OPEN, container_name="nginx", user_id=100
            ),
        ),
        (
            "__get_logs__:open:nginx:100",
            ParsedLogsCallback(
                action=LOGS_ACTION_OPEN, container_name="nginx", user_id=100
            ),
        ),
        (
            "__get_logs__:nav:sess:2:100",
            ParsedLogsCallback(
                action=LOGS_ACTION_NAV, session_id="sess", page_index=2, user_id=100
            ),
        ),
        (
            "__get_logs__:refresh:sess:100",
            ParsedLogsCallback(
                action=LOGS_ACTION_REFRESH, session_id="sess", user_id=100
            ),
        ),
        (
            "__get_logs__:file:sess:100",
            ParsedLogsCallback(action=LOGS_ACTION_FILE, session_id="sess", user_id=100),
        ),
    ],
)
def test_parse_logs_callback_data_valid(
    data: str, expected: ParsedLogsCallback
) -> None:
    assert logs_module._parse_logs_callback_data(data) == expected


@pytest.mark.parametrize(
    "data",
    [
        "bad",
        "__get_logs__",
        "__get_logs__:open",
        "__get_logs__:nav:sess:not-int:100",
        "__get_logs__:open:nginx:not-int",
    ],
)
def test_parse_logs_callback_data_invalid(data: str) -> None:
    with pytest.raises((ValueError, TypeError)):
        logs_module._parse_logs_callback_data(data)


def test_build_logs_chunks_handles_empty_and_newest_first() -> None:
    assert logs_module._build_logs_chunks("   ") == [LOGS_EMPTY_MESSAGE]

    logs = "1\n2\n3\n4\n5\n6"
    chunks = logs_module._build_logs_chunks(logs, max_chunk_chars=3)
    assert chunks[0].endswith("6")
    assert chunks[-1].startswith("1")


def test_clamp_page_index_limits_to_range() -> None:
    assert logs_module._clamp_page_index(5, 1) == 0
    assert logs_module._clamp_page_index(-1, 3) == 0
    assert logs_module._clamp_page_index(9, 3) == 2


def test_render_logs_page_without_truncation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        logs_module,
        "_render_logs_template",
        lambda logs, container_name, emojis: f"{container_name}|{logs}|{emojis['t']}",
    )
    text, truncated = logs_module._render_logs_page(
        logs_chunk="abc",
        container_name="api",
        emojis={"t": "x"},
        page_index=0,
        total_pages=2,
    )
    assert truncated is False
    assert "[Page 1/2 | Newest first]" in text


def test_render_logs_page_truncates_with_notice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(logs_module, "MAX_TELEGRAM_MESSAGE_LENGTH", 120)
    monkeypatch.setattr(
        logs_module,
        "_render_logs_template",
        lambda logs, container_name, emojis: logs,
    )
    text, truncated = logs_module._render_logs_page(
        logs_chunk="x" * 500,
        container_name="api",
        emojis={},
        page_index=0,
        total_pages=2,
    )
    assert truncated is True
    assert LOGS_TRUNCATION_NOTICE.strip() in text
    assert len(text) <= logs_module.MAX_TELEGRAM_MESSAGE_LENGTH


def test_render_logs_page_fallback_when_template_always_too_long(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(logs_module, "MAX_TELEGRAM_MESSAGE_LENGTH", 80)
    monkeypatch.setattr(
        logs_module,
        "_render_logs_template",
        lambda logs, container_name, emojis: "Z" * 500,
    )
    text, truncated = logs_module._render_logs_page(
        logs_chunk="abc",
        container_name="api",
        emojis={},
        page_index=0,
        total_pages=1,
    )
    assert truncated is True
    assert len(text) == 80


def test_validate_logs_session_access_denies_non_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(
        logs_module,
        "_is_logs_session_owner",
        lambda call, session: False,
    )
    monkeypatch.setattr(
        logs_module,
        "show_handler_info",
        lambda call, text, bot: shown.append(text),
    )
    session = _make_session(user_id=111)
    call = _DummyCall(from_user=_DummyUser(id=999))
    bot = _DummyBot()

    allowed = logs_module._validate_logs_session_access(
        call=cast(CallbackQuery, call),
        bot=cast(TeleBot, bot),
        session=session,
        requested_action=LOGS_ACTION_NAV,
    )
    assert allowed is False
    assert shown == ["Access denied: logs session belongs to another user."]


def test_validate_logs_session_access_denies_by_authorization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(
        logs_module, "_is_logs_session_owner", lambda call, session: True
    )
    monkeypatch.setattr(
        logs_module,
        "authorize_docker_callback_request",
        lambda **kwargs: (False, "Not authenticated user."),
    )
    monkeypatch.setattr(
        logs_module,
        "show_handler_info",
        lambda call, text, bot: shown.append(text),
    )
    session = _make_session(user_id=333)
    call = _DummyCall(from_user=_DummyUser(id=333))
    bot = _DummyBot()

    allowed = logs_module._validate_logs_session_access(
        call=cast(CallbackQuery, call),
        bot=cast(TeleBot, bot),
        session=session,
        requested_action=LOGS_ACTION_NAV,
    )
    assert allowed is False
    assert shown == ["Getting logs: Not authenticated user."]


def test_validate_logs_session_access_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        logs_module, "_is_logs_session_owner", lambda call, session: True
    )
    monkeypatch.setattr(
        logs_module,
        "authorize_docker_callback_request",
        lambda **kwargs: (True, ""),
    )
    session = _make_session(user_id=333)
    call = _DummyCall(from_user=_DummyUser(id=333))
    bot = _DummyBot()

    assert (
        logs_module._validate_logs_session_access(
            call=cast(CallbackQuery, call),
            bot=cast(TeleBot, bot),
            session=session,
            requested_action=LOGS_ACTION_NAV,
        )
        is True
    )


def test_build_logs_keyboard_contains_navigation_and_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        logs_module,
        "button_data",
        lambda text, callback_data: {"text": text, "callback_data": callback_data},
    )
    monkeypatch.setattr(
        logs_module,
        "keyboards",
        SimpleNamespace(build_inline_keyboard=lambda buttons: buttons),
    )
    monkeypatch.setattr(
        logs_module,
        "em",
        SimpleNamespace(get_emoji=lambda key: {"BACK_arrow": "⬅️", "house": "🏠"}[key]),
    )
    session = _make_session(session_id="sid-1", container_name="api", user_id=77)

    buttons = logs_module._build_logs_keyboard(
        session=session, current_page=1, total_pages=3
    )
    callbacks = [button["callback_data"] for button in buttons]
    assert f"{LOGS_CALLBACK_PREFIX}:nav:sid-1:0:77" in callbacks
    assert f"{LOGS_CALLBACK_PREFIX}:nav:sid-1:2:77" in callbacks
    assert "back_to_containers" in callbacks
    assert any(
        button["text"] == "As file" and ":file:sid-1:77" in button["callback_data"]
        for button in buttons
    )


def test_edit_logs_message_handles_missing_message_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(
        logs_module,
        "show_handler_info",
        lambda call, text, bot: shown.append(text),
    )
    bot = _DummyBot()
    call = _DummyCall(message=None)
    session = _make_session()

    result = logs_module._edit_logs_message(
        call=cast(CallbackQuery, call),
        bot=cast(TeleBot, bot),
        session=session,
        page_index=0,
        emojis={},
    )
    assert result is None
    assert shown == ["Cannot update logs view in this context."]


def test_edit_logs_message_edits_with_clamped_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        logs_module, "_render_logs_page", lambda **kwargs: ("CTX", False)
    )
    monkeypatch.setattr(logs_module, "_build_logs_keyboard", lambda **kwargs: "KBD")
    bot = _DummyBot()
    call = _DummyCall(message=_DummyMessage(chat=_DummyChat(id=10), message_id=20))
    session = _make_session(chunks=["new", "old"])

    result = logs_module._edit_logs_message(
        call=cast(CallbackQuery, call),
        bot=cast(TeleBot, bot),
        session=session,
        page_index=10,
        emojis={},
    )
    assert result is True
    assert bot.edited[0]["chat_id"] == 10
    assert bot.edited[0]["message_id"] == 20
    assert bot.edited[0]["parse_mode"] == "HTML"


def test_edit_logs_message_ignores_not_modified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ApiTelegramExceptionStub(Exception):
        def __init__(self, description: str, error_code: int = 400) -> None:
            super().__init__(description)
            self.description = description
            self.error_code = error_code

    monkeypatch.setattr(
        inline_common_module, "ApiTelegramException", _ApiTelegramExceptionStub
    )
    monkeypatch.setattr(
        logs_module, "_render_logs_page", lambda **kwargs: ("CTX", False)
    )
    monkeypatch.setattr(logs_module, "_build_logs_keyboard", lambda **kwargs: "KBD")

    bot = _DummyBot()
    bot.edit_message_text = lambda **kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        _ApiTelegramExceptionStub(_NOT_MODIFIED_DESCRIPTION)
    )
    call = _DummyCall(message=_DummyMessage(chat=_DummyChat(id=10), message_id=20))
    session = _make_session(chunks=["new", "old"])

    result = logs_module._edit_logs_message(
        call=cast(CallbackQuery, call),
        bot=cast(TeleBot, bot),
        session=session,
        page_index=0,
        emojis={},
    )
    assert result is False
    assert bot.callback_answers[-1]["text"] == "Logs view is already up to date."


def test_get_session_or_show_error_when_expired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(logs_module._logs_sessions, "get", lambda _sid: None)
    monkeypatch.setattr(
        logs_module,
        "show_handler_info",
        lambda call, text, bot: shown.append(text),
    )
    call = _DummyCall()
    bot = _DummyBot()

    assert (
        logs_module._get_session_or_show_error(
            cast(CallbackQuery, call), "missing", cast(TeleBot, bot)
        )
        is None
    )
    assert shown == ["Logs session expired. Open logs again from container info."]


def test_send_logs_as_file_scheduled_auto_deletion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        logs_module,
        "_validate_logs_session_access",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        logs_module.deletion_manager,
        "schedule_deletion",
        lambda **kwargs: DeletionResult(
            status=DeletionStatus.SCHEDULED,
            message_id=int(kwargs["message_id"]),
            user_id=int(kwargs["user_id"]),
            pending_count=1,
        ),
    )
    bot = _DummyBot()
    call = _DummyCall(
        from_user=_DummyUser(id=99), message=_DummyMessage(chat=_DummyChat(id=7))
    )
    session = _make_session(container_name="api", user_id=99, raw_logs="abc")

    result = logs_module._send_logs_as_file(
        call=cast(CallbackQuery, call),
        bot=cast(TeleBot, bot),
        session=session,
    )
    assert result == "callback-answered"
    assert bot.documents
    assert LOGS_FILE_DELETION_NOTICE in str(bot.documents[0]["caption"])
    assert str(bot.documents[0]["visible_file_name"]).endswith("-logs.txt")
    assert bot.callback_answers[0]["text"] == "Sent api-logs.txt. Auto-delete in 30s."


def test_send_logs_as_file_handles_limit_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        logs_module,
        "_validate_logs_session_access",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        logs_module.deletion_manager,
        "schedule_deletion",
        lambda **kwargs: DeletionResult(
            status=DeletionStatus.LIMIT_EXCEEDED,
            message_id=int(kwargs["message_id"]),
            user_id=int(kwargs["user_id"]),
            pending_count=3,
        ),
    )
    bot = _DummyBot()
    call = _DummyCall(
        from_user=_DummyUser(id=99), message=_DummyMessage(chat=_DummyChat(id=7))
    )
    session = _make_session(container_name="api", user_id=99, raw_logs="abc")

    logs_module._send_logs_as_file(
        call=cast(CallbackQuery, call),
        bot=cast(TeleBot, bot),
        session=session,
    )
    assert bot.messages
    assert "Privacy Notice" in str(bot.messages[0]["text"])
    assert "queue is full" in str(bot.callback_answers[0]["text"])


def test_send_logs_as_file_handles_unexpected_schedule_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        logs_module,
        "_validate_logs_session_access",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        logs_module.deletion_manager,
        "schedule_deletion",
        lambda **kwargs: DeletionResult(
            status=DeletionStatus.FAILED,
            message_id=int(kwargs["message_id"]),
            user_id=int(kwargs["user_id"]),
            pending_count=0,
            error_message="boom",
        ),
    )
    bot = _DummyBot()
    call = _DummyCall(
        from_user=_DummyUser(id=99), message=_DummyMessage(chat=_DummyChat(id=7))
    )
    session = _make_session(container_name="api", user_id=99, raw_logs="abc")

    logs_module._send_logs_as_file(
        call=cast(CallbackQuery, call),
        bot=cast(TeleBot, bot),
        session=session,
    )
    assert (
        bot.callback_answers[0]["text"]
        == "Sent api-logs.txt. Delete manually when done."
    )


def test_handle_get_logs_invalid_and_unsupported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(
        logs_module,
        "show_handler_info",
        lambda call, text, bot: shown.append(text),
    )
    monkeypatch.setattr(
        logs_module,
        "authorize_docker_callback_request",
        lambda call, called_user_id: (True, ""),
    )

    invalid_call = _DummyCall(data="broken")
    raw_handler = _raw_handle_get_logs()
    raw_handler(
        cast(CallbackQuery, invalid_call),
        cast(TeleBot, _DummyBot()),
    )

    monkeypatch.setattr(
        logs_module,
        "_parse_logs_callback_data",
        lambda data: ParsedLogsCallback(action="unknown", user_id=1),
    )
    unsupported_call = _DummyCall(data="__get_logs__:whatever")
    raw_handler(
        cast(CallbackQuery, unsupported_call),
        cast(TeleBot, _DummyBot()),
    )

    assert shown[0] == "Invalid logs request format"
    assert shown[1] == "Unsupported logs action"


def test_open_logs_session_handles_unsupported_logging_driver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(
        logs_module,
        "get_sanitized_logs",
        lambda container_name, call, token: (_ for _ in ()).throw(
            ContainerLogsUnavailableError(
                ErrorContext(
                    message="logs unavailable",
                    error_code="DOCKER_010",
                    metadata={"container_id": container_name},
                )
            )
        ),
    )
    monkeypatch.setattr(
        logs_module,
        "show_handler_info",
        lambda call, text, bot: shown.append(text),
    )

    logs_module._open_logs_session(
        call=cast(CallbackQuery, _DummyCall()),
        bot=cast(TeleBot, _DummyBot()),
        container_name="amnezia-dns",
        user_id=333,
        emojis={},
    )

    assert shown == [
        "amnezia-dns: This container does not provide readable logs "
        "(configured Docker logging driver does not support reading)."
    ]


def test_handle_get_logs_routes_open_nav_refresh_and_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_logs_actions(monkeypatch)

    opened: list[str] = []
    edited: list[int] = []
    sent_as_file: list[str] = []
    removed_sessions: list[str] = []
    created_sessions: list[tuple[str, int]] = []

    monkeypatch.setattr(
        logs_module,
        "_open_logs_session",
        lambda call, bot, container_name, user_id, emojis: opened.append(
            container_name
        ),
    )
    monkeypatch.setattr(
        logs_module,
        "_edit_logs_message",
        lambda call, bot, session, page_index, emojis: edited.append(page_index),
    )
    monkeypatch.setattr(
        logs_module,
        "_send_logs_as_file",
        lambda call, bot, session: sent_as_file.append(session.session_id),
    )

    old_session = _make_session(session_id="s1", container_name="api", user_id=333)
    refreshed_session = _make_session(
        session_id="s2", container_name="api", user_id=333
    )
    monkeypatch.setattr(
        logs_module,
        "_get_session_or_show_error",
        lambda call, session_id, bot: old_session if session_id == "s1" else None,
    )
    monkeypatch.setattr(
        logs_module,
        "get_sanitized_logs",
        lambda container_name, call, token: "fresh logs",
    )
    monkeypatch.setattr(
        logs_module._logs_sessions,
        "remove",
        lambda session_id: removed_sessions.append(session_id),
    )

    def _create_session(
        container_name: str,
        user_id: int,
        raw_logs: str,
        chunks: list[str],
    ) -> LogsSession:
        del raw_logs, chunks
        created_sessions.append((container_name, user_id))
        return refreshed_session

    monkeypatch.setattr(logs_module._logs_sessions, "create", _create_session)

    bot = _DummyBot()
    raw_handler = _raw_handle_get_logs()
    call_open = _DummyCall(data=f"{LOGS_CALLBACK_PREFIX}:open:api:333")
    raw_handler(
        cast(CallbackQuery, call_open),
        cast(TeleBot, bot),
    )

    call_nav = _DummyCall(data=f"{LOGS_CALLBACK_PREFIX}:nav:s1:2:333")
    raw_handler(
        cast(CallbackQuery, call_nav),
        cast(TeleBot, bot),
    )

    call_refresh = _DummyCall(data=f"{LOGS_CALLBACK_PREFIX}:refresh:s1:333")
    raw_handler(
        cast(CallbackQuery, call_refresh),
        cast(TeleBot, bot),
    )

    call_file = _DummyCall(data=f"{LOGS_CALLBACK_PREFIX}:file:s1:333")
    raw_handler(
        cast(CallbackQuery, call_file),
        cast(TeleBot, bot),
    )

    assert opened == ["api"]
    assert 2 in edited and 0 in edited
    assert sent_as_file == ["s1"]
    assert removed_sessions == ["s1"]
    assert created_sessions == [("api", 333)]


def test_handle_get_logs_refresh_handles_unsupported_logging_driver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _allow_logs_actions(monkeypatch)

    shown: list[str] = []
    removed_sessions: list[str] = []
    old_session = _make_session(session_id="s1", container_name="api", user_id=333)

    monkeypatch.setattr(
        logs_module,
        "_get_session_or_show_error",
        lambda call, session_id, bot: old_session if session_id == "s1" else None,
    )
    monkeypatch.setattr(
        logs_module,
        "get_sanitized_logs",
        lambda container_name, call, token: (_ for _ in ()).throw(
            ContainerLogsUnavailableError(
                ErrorContext(
                    message="logs unavailable",
                    error_code="DOCKER_010",
                    metadata={"container_id": container_name},
                )
            )
        ),
    )
    monkeypatch.setattr(
        logs_module,
        "show_handler_info",
        lambda call, text, bot: shown.append(text),
    )
    monkeypatch.setattr(
        logs_module._logs_sessions,
        "remove",
        lambda session_id: removed_sessions.append(session_id),
    )

    raw_handler = _raw_handle_get_logs()
    raw_handler(
        cast(CallbackQuery, _DummyCall(data=f"{LOGS_CALLBACK_PREFIX}:refresh:s1:333")),
        cast(TeleBot, _DummyBot()),
    )

    assert shown == [
        "api: This container does not provide readable logs "
        "(configured Docker logging driver does not support reading)."
    ]
    assert removed_sessions == []


def test_send_logs_as_file_no_message_or_empty_logs_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(
        logs_module,
        "_validate_logs_session_access",
        lambda **kwargs: True,
    )
    monkeypatch.setattr(
        logs_module,
        "show_handler_info",
        lambda call, text, bot: shown.append(text),
    )
    bot = _DummyBot()

    no_message_call = _DummyCall(message=None)
    session = _make_session(raw_logs="abc")
    logs_module._send_logs_as_file(
        call=cast(CallbackQuery, no_message_call),
        bot=cast(TeleBot, bot),
        session=session,
    )
    assert shown[0] == "Cannot send logs file in this context."

    with_message_call = _DummyCall()
    empty_logs_session = _make_session(raw_logs="  ")
    logs_module._send_logs_as_file(
        call=cast(CallbackQuery, with_message_call),
        bot=cast(TeleBot, bot),
        session=empty_logs_session,
    )
    assert shown[1] == "container: No logs available"


def test_send_logs_as_file_includes_expected_schedule_delay(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_delay: list[int] = []
    monkeypatch.setattr(
        logs_module, "_validate_logs_session_access", lambda **kwargs: True
    )

    def _schedule(
        *,
        bot: TeleBot,
        chat_id: int,
        message_id: int,
        user_id: int,
        delay_seconds: int,
        callback: Callable[[DeletionResult], None],
    ) -> DeletionResult:
        del bot, chat_id, callback
        captured_delay.append(delay_seconds)
        return DeletionResult(
            status=DeletionStatus.ALREADY_SCHEDULED,
            message_id=message_id,
            user_id=user_id,
            pending_count=1,
        )

    monkeypatch.setattr(logs_module.deletion_manager, "schedule_deletion", _schedule)
    bot = _DummyBot()
    call = _DummyCall(
        from_user=_DummyUser(id=77), message=_DummyMessage(chat=_DummyChat(id=9))
    )
    session = _make_session(container_name="nginx", user_id=77, raw_logs="abc")
    logs_module._send_logs_as_file(
        call=cast(CallbackQuery, call),
        bot=cast(TeleBot, bot),
        session=session,
    )

    assert captured_delay == [LOGS_FILE_AUTO_DELETE_DELAY_SECONDS]
    assert bot.callback_answers[0]["text"] == "Sent nginx-logs.txt. Auto-delete in 30s."
