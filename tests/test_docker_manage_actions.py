"""Manage screen and container actions: confirmation, immediate answer, results."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import cast

import pytest
from telebot import TeleBot
from telebot.apihelper import ApiTelegramException
from telebot.types import CallbackQuery, InlineKeyboardMarkup

import pytmbot.handlers.docker_handlers.inline.manage as manage_module
import pytmbot.handlers.docker_handlers.inline.manage_action as action_module
import pytmbot.handlers.handlers_util.callback_auth as callback_auth_module
import pytmbot.middleware.session_wrapper as session_wrapper_module
from pytmbot.exceptions import (
    ContainerActionInProgressError,
    ContainerNotFoundError,
    ContainerStateConflictError,
    DockerConnectionError,
    DockerOperationException,
    InvalidContainerReferenceError,
)
from pytmbot.handlers.docker_handlers.user_messages import (
    CONTAINER_NOT_FOUND_TEXT,
    DOCKER_REQUEST_FAILED_TEXT,
    DOCKER_UNAVAILABLE_TEXT,
    INVALID_CONTAINER_REF_TEXT,
)
from tests._telebot_objects import PayloadDict, telegram_object_from_payload

_ADMIN = 123456789  # allowed admin in pytmbot.yaml.sample


class _ApiError(ApiTelegramException):
    """Typed stand-in for a Telegram API error."""

    def __init__(self, description: str) -> None:
        Exception.__init__(self, description)
        self.description = description
        self.error_code = 400


_CONTAINER_ID = "1a2b3c4d5e6f"
type _Event = tuple[str, dict[str, object]]


def _make_call(data: str, *, user_id: int = _ADMIN) -> CallbackQuery:
    payload: PayloadDict = {
        "id": "cbq-1",
        "from": {"id": user_id, "is_bot": False, "first_name": "Admin"},
        "chat_instance": "ci",
        "data": data,
        "message": {
            "message_id": 4242,
            "date": 0,
            "chat": {"id": user_id, "type": "private"},
            "from": {"id": 1111, "is_bot": True, "first_name": "bot"},
            "text": "container",
        },
    }
    return telegram_object_from_payload(
        payload,
        parser=cast(Callable[[PayloadDict], CallbackQuery], CallbackQuery.de_json),
        expected_type=CallbackQuery,
    )


@dataclass
class _RecordingBot:
    token: str = "1111:TEST"
    events: list[_Event] = field(default_factory=list)
    answer_error: ApiTelegramException | None = None

    def answer_callback_query(
        self,
        callback_query_id: str,
        text: str | None = None,
        show_alert: bool | None = None,
        **kwargs: object,
    ) -> bool:
        del kwargs
        self.events.append(
            ("answer", {"id": callback_query_id, "text": text, "alert": show_alert})
        )
        if self.answer_error is not None:
            raise self.answer_error
        return True

    def edit_message_text(self, **kwargs: object) -> bool:
        self.events.append(("edit", dict(kwargs)))
        return True

    def answers(self) -> list[dict[str, object]]:
        return [payload for kind, payload in self.events if kind == "answer"]

    def edits(self) -> list[dict[str, object]]:
        return [payload for kind, payload in self.events if kind == "edit"]


def _html(edit: dict[str, object]) -> str:
    return str(getattr(edit["rich_message"], "html", ""))


def _callbacks(edit: dict[str, object]) -> list[str]:
    markup = edit.get("reply_markup")
    if not isinstance(markup, InlineKeyboardMarkup):
        return []
    return [str(button.callback_data) for row in markup.keyboard for button in row]


@dataclass
class _FakeDocker:
    """Containers by exact short ID; any other reference is not found."""

    states: dict[str, str] = field(default_factory=lambda: {_CONTAINER_ID: "running"})
    lookup_error: Exception | None = None
    action_error: Exception | None = None
    actions: list[tuple[int, str, str]] = field(default_factory=list)

    def fetch(self, container_ref: str) -> SimpleNamespace | None:
        if self.lookup_error is not None:
            raise self.lookup_error
        state = self.states.get(container_ref)
        if state is None:
            return None
        return SimpleNamespace(id=container_ref + "0" * 52, name="web", status=state)

    def state(self, container_ref: str) -> str | None:
        if self.lookup_error is not None:
            raise self.lookup_error
        return self.states.get(container_ref)

    def managing_container(self, user_id: int, ref: str, action: str) -> None:
        self.actions.append((user_id, ref, action))
        if self.action_error is not None:
            raise self.action_error
        self.states[ref] = "exited" if action == "stop" else "running"


@pytest.fixture
def docker(monkeypatch: pytest.MonkeyPatch) -> _FakeDocker:
    fake = _FakeDocker()
    session = SimpleNamespace(
        is_authenticated=lambda user_id: True,
        set_referer_data=lambda *args: None,
    )
    monkeypatch.setattr(session_wrapper_module, "session_manager", session)
    monkeypatch.setattr(callback_auth_module, "session_manager", session)
    monkeypatch.setattr(manage_module, "fetch_full_container_details", fake.fetch)
    monkeypatch.setattr(action_module, "get_container_state", fake.state)
    monkeypatch.setattr(action_module, "container_manager", fake)
    monkeypatch.setattr(action_module, "_run_in_background", lambda job: job())
    return fake


def _press(data: str, bot: _RecordingBot | None = None) -> _RecordingBot:
    recording_bot = bot or _RecordingBot()
    handler = cast(
        Callable[[CallbackQuery, TeleBot], object],
        manage_module.handle_manage_container
        if data.startswith("__manage__")
        else action_module.handle_manage_container_action,
    )
    handler(_make_call(data), cast(TeleBot, recording_bot))
    return recording_bot


@pytest.mark.parametrize(
    ("state", "expected_prefixes", "hint"),
    [
        ("running", ["__stop__", "__restart__"], None),
        ("restarting", ["__stop__"], None),
        ("created", ["__start__"], None),
        ("exited", ["__start__"], None),
        ("paused", ["__stop__", "__restart__"], None),
        ("dead", [], "is dead"),
        ("removing", [], "being removed"),
    ],
)
def test_manage_view_offers_actions_per_state(
    docker: _FakeDocker, state: str, expected_prefixes: list[str], hint: str | None
) -> None:
    docker.states[_CONTAINER_ID] = state
    bot = _press(f"__manage__:{_CONTAINER_ID}:{_ADMIN}")

    edit = bot.edits()[-1]
    callbacks = _callbacks(edit)
    assert [value.split(":", 1)[0] for value in callbacks[:-1]] == expected_prefixes
    assert callbacks[-1] == f"__get_full__:{_CONTAINER_ID}:{_ADMIN}"
    assert all(f":{_CONTAINER_ID}:{_ADMIN}" in value for value in callbacks)
    if hint is not None:
        assert hint in _html(edit)


@pytest.mark.parametrize(
    ("error", "expected_text"),
    [
        (None, CONTAINER_NOT_FOUND_TEXT),
        (DockerConnectionError("down"), DOCKER_UNAVAILABLE_TEXT),
        (InvalidContainerReferenceError("bad"), INVALID_CONTAINER_REF_TEXT),
        (DockerOperationException("api error"), DOCKER_REQUEST_FAILED_TEXT),
    ],
)
def test_manage_view_reports_lookup_failures(
    docker: _FakeDocker, error: Exception | None, expected_text: str
) -> None:
    docker.lookup_error = error
    ref = "db" if error is None else _CONTAINER_ID  # old lower-cased name button
    bot = _press(f"__manage__:{ref}:{_ADMIN}")
    assert bot.edits() == []
    assert bot.answers()[-1] == {"id": "cbq-1", "text": expected_text, "alert": True}


@pytest.mark.parametrize(
    ("prefix", "confirm_prefix", "question"),
    [
        ("__stop__", "__stop_confirm__", "Stop web?"),
        ("__restart__", "__restart_confirm__", "Restart web?"),
    ],
)
def test_stop_and_restart_ask_for_confirmation(
    docker: _FakeDocker, prefix: str, confirm_prefix: str, question: str
) -> None:
    bot = _press(f"{prefix}:{_CONTAINER_ID}:{_ADMIN}")

    assert docker.actions == []
    edit = bot.edits()[-1]
    assert question in _html(edit)
    assert _callbacks(edit) == [
        f"{confirm_prefix}:{_CONTAINER_ID}:{_ADMIN}",
        f"__manage__:{_CONTAINER_ID}:{_ADMIN}",
    ]


def test_confirmed_stop_answers_first_then_reports_refreshed_state(
    docker: _FakeDocker,
) -> None:
    bot = _press(f"__stop_confirm__:{_CONTAINER_ID}:{_ADMIN}")

    assert docker.actions == [(_ADMIN, _CONTAINER_ID, "stop")]
    kinds = [kind for kind, _ in bot.events]
    assert kinds == ["answer", "edit", "edit"]
    assert bot.answers()[0] == {"id": "cbq-1", "text": "Stopping web…", "alert": False}

    progress, result = bot.edits()
    assert "Stopping web" in _html(progress)
    assert _callbacks(progress) == []  # no buttons while the action runs
    assert "web stopped. Current state: exited." in _html(result)
    assert _callbacks(result) == [
        f"__start__:{_CONTAINER_ID}:{_ADMIN}",
        f"__get_full__:{_CONTAINER_ID}:{_ADMIN}",
    ]


def test_start_runs_without_confirmation(docker: _FakeDocker) -> None:
    docker.states[_CONTAINER_ID] = "exited"
    bot = _press(f"__start__:{_CONTAINER_ID}:{_ADMIN}")
    assert docker.actions == [(_ADMIN, _CONTAINER_ID, "start")]
    assert "web started. Current state: running." in _html(bot.edits()[-1])


@pytest.mark.parametrize(
    ("data", "error", "expected"),
    [
        (
            "__restart_confirm__",
            ContainerActionInProgressError("busy"),
            "An action on web is already in progress.",
        ),
        (
            "__stop_confirm__",
            ContainerStateConflictError("conflict", state="exited"),
            "web is already stopped (state: exited).",
        ),
        (
            "__start__",
            ContainerStateConflictError("conflict", state="running"),
            "web is already running (state: running).",
        ),
        (
            "__restart_confirm__",
            ContainerStateConflictError("conflict"),
            "web can't be restarted right now.",
        ),
        (
            "__stop_confirm__",
            ContainerNotFoundError("gone"),
            "web was not found. It may have been removed or recreated.",
        ),
        ("__stop_confirm__", DockerConnectionError("down"), DOCKER_UNAVAILABLE_TEXT),
        (
            "__stop_confirm__",
            InvalidContainerReferenceError("bad"),
            INVALID_CONTAINER_REF_TEXT,
        ),
        (
            "__stop_confirm__",
            PermissionError("Rate limit exceeded. Wait 1.0s between operations"),
            "Can't stop web: Rate limit exceeded. Wait 1.0s between operations",
        ),
        (
            "__start__",
            ContainerStateConflictError("conflict", state="paused"),
            "web can't be started right now (state: paused).",
        ),
        (
            "__stop_confirm__",
            ContainerStateConflictError("conflict", state="removing"),
            "web can't be stopped right now (state: removing).",
        ),
        (
            "__stop_confirm__",
            ContainerStateConflictError("conflict", state="created"),
            "web is already stopped (state: created).",
        ),
        (
            "__restart_confirm__",
            DockerOperationException("api error"),
            "Docker couldn't restart web. See the bot logs for details.",
        ),
        (
            "__stop_confirm__",
            RuntimeError("boom"),
            "Couldn't stop web: Docker reported an error. See the bot logs.",
        ),
    ],
)
def test_action_errors_are_reported_honestly(
    docker: _FakeDocker, data: str, error: Exception, expected: str
) -> None:
    docker.action_error = error
    bot = _press(f"{data}:{_CONTAINER_ID}:{_ADMIN}")

    result = _html(bot.edits()[-1])
    assert expected.replace("'", "&#39;") in result
    assert "Unexpected error" not in result
    # The refreshed Manage buttons are shown again after a failure.
    assert _callbacks(bot.edits()[-1])[-1] == f"__get_full__:{_CONTAINER_ID}:{_ADMIN}"


def test_action_result_survives_docker_outage_on_refresh(
    docker: _FakeDocker, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refresh_fails(container_ref: str) -> None:
        raise DockerOperationException(f"api error while reading {container_ref}")

    # The lookup before the action works; the refresh after it does not.
    monkeypatch.setattr(action_module, "get_container_state", refresh_fails)
    bot = _press(f"__stop_confirm__:{_CONTAINER_ID}:{_ADMIN}")
    assert docker.actions == [(_ADMIN, _CONTAINER_ID, "stop")]
    assert "web stopped. Current state: unknown." in _html(bot.edits()[-1])


def test_old_name_based_action_button_never_acts(docker: _FakeDocker) -> None:
    bot = _press(f"__stop_confirm__:db:{_ADMIN}")
    assert docker.actions == []
    assert bot.answers()[-1]["text"] == CONTAINER_NOT_FOUND_TEXT


@pytest.mark.parametrize(
    "data",
    [
        f"__stop_confirm__:{_CONTAINER_ID}:{_ADMIN}:extra",
        f"__stop_confirm__:../etc:{_ADMIN}",
    ],
)
def test_malformed_action_payloads_are_rejected(docker: _FakeDocker, data: str) -> None:
    bot = _press(data)
    assert docker.actions == []
    assert bot.edits() == []
    assert bot.answers()[-1]["alert"] is True


def test_expired_callback_answer_does_not_cancel_confirmed_action(
    docker: _FakeDocker,
) -> None:
    bot = _RecordingBot(answer_error=_ApiError("Bad Request: query is too old"))
    _press(f"__stop_confirm__:{_CONTAINER_ID}:{_ADMIN}", bot)
    assert docker.actions == [(_ADMIN, _CONTAINER_ID, "stop")]


def test_edit_after_answer_logs_telegram_errors(docker: _FakeDocker) -> None:
    del docker

    class _FailingBot(_RecordingBot):
        def edit_message_text(self, **kwargs: object) -> bool:
            raise _ApiError("Bad Request: message to edit not found")

    action_module._edit_after_answer(
        _make_call(f"__stop_confirm__:{_CONTAINER_ID}:{_ADMIN}"),
        cast(TeleBot, _FailingBot()),
        "<p><b>x</b></p>",
        reply_markup=None,
    )


def test_managing_action_fabric_matches_exact_prefixes() -> None:
    def matches(data: str | None) -> bool:
        return action_module.managing_action_fabric(
            cast(CallbackQuery, SimpleNamespace(data=data))
        )

    for prefix in (
        "__start__",
        "__stop__",
        "__restart__",
        "__stop_confirm__",
        "__restart_confirm__",
    ):
        assert matches(f"{prefix}:{_CONTAINER_ID}:1")
    assert not matches("__start__x:1:1")
    assert not matches("__manage__:1:1")
    assert not matches(None)


def test_background_jobs_run_in_pool_and_failures_are_logged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    logged: list[str] = []
    monkeypatch.setattr(
        action_module,
        "logger",
        SimpleNamespace(error=lambda message, **kwargs: logged.append(message)),
    )
    done: list[str] = []
    action_module._run_in_background(lambda: done.append("ran"))
    action_module._action_executor.submit(lambda: None).result(timeout=5)
    assert done == ["ran"]

    failed: Future[None] = Future()
    failed.set_exception(RuntimeError("boom"))
    action_module._log_background_failure(failed)
    cancelled: Future[None] = Future()
    cancelled.cancel()
    action_module._log_background_failure(cancelled)
    assert logged == ["bot.handler.docker.manage_action.background.fail"]
