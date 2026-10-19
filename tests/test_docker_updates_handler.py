"""The "Check updates" button: background check, single flight and report."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import cast

import pytest
from telebot import TeleBot
from telebot.apihelper import ApiTelegramException
from telebot.types import CallbackQuery

import pytmbot.handlers.docker_handlers.inline.image_updates as image_updates
from pytmbot.adapters.docker.updates import (
    CHECK_DEADLINE,
    UpdaterResponse,
    UpdaterStatus,
)
from pytmbot.globals import settings
from pytmbot.handlers.handlers_util.rich_messages import build_rich_html_message
from pytmbot.parsers.compiler import Compiler
from pytmbot.utils.rich_html import (
    find_rich_html_issues,
    measure_rich_html,
    rich_html_to_plain_text,
)
from tests._inline_edit_helpers import assert_reply_markup_has_callbacks
from tests._telebot_objects import (
    PayloadDict,
    PayloadValue,
    record_callback_answer,
    record_edited_message,
    unwrap_handler,
)

OWNER_ID = next(iter(settings.access_control.allowed_user_ids))
WAIT_SECONDS = 5.0


@dataclass
class _User:
    id: int = OWNER_ID


@dataclass
class _Chat:
    id: int = 22


@dataclass
class _Message:
    chat: _Chat = field(default_factory=_Chat)
    message_id: int = 33


@dataclass
class _Call:
    id: str = "cb"
    data: str | None = f"__check_updates__:{OWNER_ID}"
    from_user: _User | None = field(default_factory=_User)
    message: _Message | None = field(default_factory=_Message)


@dataclass
class _Bot:
    callback_answers: list[PayloadDict] = field(default_factory=list)
    edited_messages: list[PayloadDict] = field(default_factory=list)
    edited: threading.Event = field(default_factory=threading.Event)
    edit_error: ApiTelegramException | None = None

    def answer_callback_query(
        self, callback_query_id: str, **kwargs: PayloadValue
    ) -> bool:
        record_callback_answer(self.callback_answers, callback_query_id, **kwargs)
        return True

    def edit_message_text(self, **kwargs: PayloadValue) -> str:
        if self.edit_error is not None:
            raise self.edit_error
        record_edited_message(self.edited_messages, **kwargs)
        self.edited.set()
        return "edited"

    def edited_html(self) -> str:
        rich = self.edited_messages[-1].get("rich_message")
        return str(getattr(rich, "html", rich))


class _MessageGone(ApiTelegramException):
    def __init__(self) -> None:
        Exception.__init__(self, "message to edit not found")
        self.error_code = 400
        self.description = "Bad Request: message to edit not found"


class _FakeUpdater:
    def __init__(
        self,
        response: UpdaterResponse,
        *,
        gate: threading.Event | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.gate = gate
        self.error = error
        self.started = threading.Event()
        self.calls = 0

    def check_updates(self, deadline: float) -> UpdaterResponse:
        assert deadline == CHECK_DEADLINE
        self.calls += 1
        self.started.set()
        if self.gate is not None:
            assert self.gate.wait(WAIT_SECONDS)
        if self.error is not None:
            raise self.error
        return self.response


_handler = cast(
    Callable[[CallbackQuery, TeleBot], None],
    unwrap_handler(image_updates.handle_image_updates, depth=3),
)


def _click(bot: _Bot, call: _Call | None = None) -> None:
    _handler(cast(CallbackQuery, call or _Call()), cast(TeleBot, bot))


def _response(
    data: dict[str, object] | None = None,
    *,
    status: UpdaterStatus = UpdaterStatus.SUCCESS,
    **metadata: object,
) -> UpdaterResponse:
    return UpdaterResponse(status=status, message="", data=data, metadata=metadata)


def _update(current: str, newer: str) -> dict[str, str]:
    return {
        "current_tag": current,
        "newer_tag": newer,
        "created_at_local": "2026-01-01T00:00:00Z",
        "created_at_remote": "2026-02-01T00:00:00Z",
        "current_digest": "",
    }


def _failure(text: str, **extra: object) -> dict[str, object]:
    return {"updates": [], "error": text, **extra}


@pytest.fixture
def worker(monkeypatch: pytest.MonkeyPatch) -> image_updates._SingleFlightWorker:
    fresh = image_updates._SingleFlightWorker("test_docker_updates_check")
    monkeypatch.setattr(image_updates, "_check_worker", fresh)
    return fresh


def _use_updater(monkeypatch: pytest.MonkeyPatch, updater: _FakeUpdater) -> None:
    monkeypatch.setattr(image_updates, "get_image_updater", lambda: updater)


def test_click_is_answered_at_once_and_checked_in_background(
    monkeypatch: pytest.MonkeyPatch, worker: image_updates._SingleFlightWorker
) -> None:
    gate = threading.Event()
    updater = _FakeUpdater(
        _response({"nginx:1.25": {"updates": [_update("1.25", "1.27")]}}), gate=gate
    )
    _use_updater(monkeypatch, updater)
    bot = _Bot()

    started = time.monotonic()
    _click(bot)
    assert time.monotonic() - started < 1  # the Telegram worker is not blocked
    assert updater.started.wait(WAIT_SECONDS)
    assert bot.callback_answers == [
        {
            "callback_query_id": "cb",
            "text": image_updates.CHECK_STARTED_TEXT,
            "show_alert": False,
        }
    ]
    assert bot.edited_messages == []

    _click(bot, _Call(id="cb2"))
    assert bot.callback_answers[-1]["text"] == "A check is already running"
    assert updater.calls == 1

    gate.set()
    assert bot.edited.wait(WAIT_SECONDS)
    html = bot.edited_html()
    assert "<code>nginx:1.25</code>" in html
    assert "1.27" in html
    assert len(bot.callback_answers) == 2  # nothing answered twice
    assert_reply_markup_has_callbacks(
        bot.edited_messages[-1].get("reply_markup"),
        expected_callbacks=[
            f"__check_updates__:{OWNER_ID}",
            f"__images_page__:1:{OWNER_ID}",
        ],
    )


def test_other_users_cannot_start_a_check(
    monkeypatch: pytest.MonkeyPatch, worker: image_updates._SingleFlightWorker
) -> None:
    updater = _FakeUpdater(_response({}))
    _use_updater(monkeypatch, updater)
    bot = _Bot()

    _click(bot, _Call(from_user=_User(id=OWNER_ID + 1)))
    _click(bot, _Call(data="__check_updates__:oops"))

    assert [answer["text"] for answer in bot.callback_answers] == [
        "You don't have access to this action.",
        "This image updates button is no longer valid.",
    ]
    assert all(answer["show_alert"] is True for answer in bot.callback_answers)
    assert updater.calls == 0


def test_single_flight_worker_runs_one_job_at_a_time() -> None:
    worker = image_updates._SingleFlightWorker("test_single_flight")
    gate = threading.Event()
    ran: list[str] = []
    done = threading.Event()

    def _blocking_job() -> None:
        ran.append(threading.current_thread().name)
        assert gate.wait(WAIT_SECONDS)

    def _failing_job() -> None:
        raise RuntimeError("boom")

    def _last_job() -> None:
        ran.append(threading.current_thread().name)
        done.set()

    assert worker.try_start(_blocking_job) is True
    assert worker.try_start(_last_job) is False
    gate.set()

    # A failing job is logged and frees the worker for the next one.
    for job in (_failing_job, _last_job):
        deadline = time.monotonic() + WAIT_SECONDS
        while not worker.try_start(job):
            assert time.monotonic() < deadline
            threading.Event().wait(0.01)

    assert done.wait(WAIT_SECONDS)
    assert ran == ["test_single_flight", "test_single_flight"]


def test_unexpected_check_errors_still_update_the_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_updater(
        monkeypatch, _FakeUpdater(_response(), error=RuntimeError("unexpected"))
    )
    bot = _Bot()

    image_updates._run_update_check(cast(CallbackQuery, _Call()), cast(TeleBot, bot), 7)

    assert image_updates.NOTICE_ERROR in rich_html_to_plain_text(bot.edited_html())
    assert bot.callback_answers == []


def test_failed_edits_are_logged_not_raised(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_updater(monkeypatch, _FakeUpdater(_response({"redis:7": {"updates": []}})))
    bot = _Bot(edit_error=_MessageGone())

    image_updates._run_update_check(cast(CallbackQuery, _Call()), cast(TeleBot, bot), 7)

    assert bot.edited_messages == []
    assert bot.callback_answers == []


def _report_html(response: UpdaterResponse) -> str:
    html = image_updates.render_update_report(response)
    assert find_rich_html_issues(html) == []
    assert html.strip().startswith("<p><b>")
    assert html.strip().endswith("</footer>")
    return html


def test_report_lists_updates_up_to_date_and_failed_images() -> None:
    response = _response(
        {
            "nginx:1.25.3-alpine": {
                "updates": [
                    _update("1.25.3-alpine", "1.25.5-alpine"),
                    _update("1.25.3-alpine", "1.25.4-alpine"),
                ]
            },
            "nginx:latest": {"updates": [_update("latest", "latest")]},
            "redis:7.2": {"updates": []},
            "postgres:16": _failure("timeout", reason="TIMEOUT"),
            "acme/app:1": _failure("rate limited", retry_after=120),
            "acme/gone:1": _failure("not found"),
            "registry.corp.example:5000/acme/payments:2.3.1": _failure(
                "registry not supported"
            ),
            "myapp:dev": _failure("local image"),
        },
        status=UpdaterStatus.PARTIAL_SUCCESS,
        rate_limited_repos=["acme/app:1"],
        retry_after=120,
    )

    text = rich_html_to_plain_text(_report_html(response))

    assert "Docker Hub rate limit reached. Try again in 2 min." in text
    assert "1.25.5-alpine" in text and "1.25.4-alpine" in text
    assert "latest (new image)" in text
    up_to_date = text.split("Up to date", 1)[1].split("Couldn't check", 1)[0]
    assert "redis:7.2" in up_to_date
    assert "postgres" not in up_to_date and "myapp" not in up_to_date
    failed = text.split("Couldn't check", 1)[1]
    for line in (
        "acme/app:1 — rate limited",
        "acme/gone:1 — not found",
        "myapp:dev — local image",
        "postgres:16 — timeout",
        "registry.corp.example:5000/acme/payments:2.3.1 — registry not supported",
    ):
        assert line in failed
    assert "Checked " in text


def test_report_escapes_registry_strings() -> None:
    response = _response(
        {
            "evil/<img src=x>:1": {"updates": [_update("1", "2<b>")]},
            "other:1": _failure("<script>alert(1)</script>"),
        }
    )

    html = _report_html(response)

    assert "<img" not in html and "<script>" not in html
    assert "evil/&lt;img src=x&gt;:1" in html
    assert "2&lt;b&gt;" in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_failed_checks_are_not_reported_as_up_to_date() -> None:
    context = image_updates.prepare_context_for_render(
        image_updates._extract_repository_updates(
            {
                "redis:7": {"updates": []},
                "postgres:16": _failure("timeout"),
                "broken": "not-a-dict",
                "missing-updates": {"total_found": 0},
            }
        )
    )

    assert context["no_updates"] == ["redis:7"]
    assert context["failed"] == [{"name": "postgres:16", "reason": "timeout"}]
    assert context["updates"] == {}


def test_updates_are_grouped_per_local_tag_without_duplicates() -> None:
    context = image_updates.prepare_context_for_render(
        image_updates._extract_repository_updates(
            {
                "nginx": {
                    "updates": [
                        _update("1.25", "1.27"),
                        _update("1.26", "1.27"),
                        _update("1.25", "1.27"),
                        _update("1.25", "1.26"),
                        {"current_tag": "1.25"},
                    ]
                }
            }
        )
    )

    groups = context["updates"]["nginx"]["groups"]
    assert [
        (group["current_tag"], [u["newer_tag"] for u in group["updates"]])
        for group in groups
    ] == [("1.25", ["1.27", "1.26"]), ("1.26", ["1.27"])]

    html = Compiler.quick_render(template_name="d_updates.jinja2", **context)
    assert find_rich_html_issues(html) == []
    assert html.count("<i>(current)</i>") == 2
    assert html.count("<b>1.27</b>") == 2


def test_new_template_sections_render_through_the_compiler() -> None:
    html = Compiler.quick_render(
        template_name="d_updates.jinja2",
        updates={},
        no_updates=[],
        failed=[{"name": "ghcr.io/acme/app:1", "reason": "registry not supported"}],
        notice=image_updates.NOTICE_PARTIAL_TIMEOUT,
        checked_at="2026-10-19 10:00:00 UTC",
    )

    assert find_rich_html_issues(html) == []
    assert "<p><b>Couldn't check</b></p>" in html
    notice = html.split("<p><i>", 1)[1].split("</i></p>", 1)[0]
    assert rich_html_to_plain_text(f"<p>{notice}</p>") == (
        image_updates.NOTICE_PARTIAL_TIMEOUT
    )
    assert html.strip().endswith("<footer>Checked 2026-10-19 10:00:00 UTC</footer>")
    assert "Pull a newer tag" not in html


@pytest.mark.parametrize(
    ("response", "notice"),
    [
        (
            _response(status=UpdaterStatus.VALIDATION_ERROR),
            image_updates.NOTICE_NO_IMAGES,
        ),
        (
            _response(status=UpdaterStatus.DOCKER_ERROR),
            image_updates.NOTICE_DOCKER_ERROR,
        ),
        (
            _response(status=UpdaterStatus.ERROR, deadline_exceeded=True),
            "The check took longer than 60 s and was stopped. Try again later.",
        ),
        (
            _response({"a:1": _failure("timeout")}, deadline_exceeded=True),
            image_updates.NOTICE_PARTIAL_TIMEOUT,
        ),
        (_response(status=UpdaterStatus.ERROR), image_updates.NOTICE_ERROR),
        (
            _response({"a:1": _failure("rate limited")}, rate_limited_repos=["a:1"]),
            "Docker Hub rate limit reached. Try again later.",
        ),
        (
            _response(
                {"a:1": _failure("rate limited")},
                rate_limited_repos=["a:1"],
                retry_after=30,
            ),
            "Docker Hub rate limit reached. Try again in 30 s.",
        ),
        (
            _response(
                {"a:1": _failure("rate limited")},
                rate_limited_repos=["a:1"],
                retry_after=7200,
            ),
            "Docker Hub rate limit reached. Try again in 2 h.",
        ),
        (_response({"a:1": {"updates": []}}), ""),
    ],
)
def test_report_notice(response: UpdaterResponse, notice: str) -> None:
    assert image_updates._report_notice(response) == notice
    if notice:
        assert notice in rich_html_to_plain_text(_report_html(response))


def test_large_reports_fit_telegram_limits() -> None:
    data: dict[str, object] = {
        f"acme/app{index}:1.0.0": {
            "updates": [_update("1.0.0", f"1.0.{patch}") for patch in range(1, 11)]
        }
        for index in range(300)
    }
    html = image_updates.render_update_report(_response(data))
    assert not measure_rich_html(html).fits

    message = build_rich_html_message(html)

    assert message.html is not None
    assert measure_rich_html(message.html).fits
    assert find_rich_html_issues(message.html) == []
