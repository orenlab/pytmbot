"""Trivy HTTP integration and database/report safety regression tests."""

from __future__ import annotations

import io
import json
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from types import SimpleNamespace
from typing import cast
from urllib.request import Request

import pytest
from pydantic import ValidationError
from telebot import TeleBot
from telebot.types import CallbackQuery, InlineKeyboardMarkup, Message

from pytmbot.globals import settings
from pytmbot.models.settings_model import TrivyConfig
from pytmbot.plugins.trivy import plugin as plugin_module
from pytmbot.plugins.trivy import runner
from pytmbot.plugins.trivy.history import HistoryDelta, HistoryError, ScanHistory
from pytmbot.plugins.trivy.plugin import (
    TrivyPlugin,
    render_failure,
    render_history,
    render_queued,
    render_report,
)
from pytmbot.plugins.trivy.runner import (
    ScanError,
    ScanJob,
    ScanQueue,
    ScanSummary,
    parse_report,
)
from pytmbot.utils.rich_html import find_rich_html_issues

_BOT_TOKEN = "12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE"


def config() -> TrivyConfig:
    return TrivyConfig(
        enabled=True,
        endpoint="http://trivy-worker:8090",
        token_file="/run/secrets/trivy_worker_token",
        timeout_seconds=30,
        max_images=5,
    )


def _new_bot() -> TeleBot:
    return TeleBot(_BOT_TOKEN)


def _capture_answers(monkeypatch: pytest.MonkeyPatch, bot: TeleBot) -> list[str]:
    answers: list[str] = []
    monkeypatch.setattr(
        bot,
        "answer_callback_query",
        lambda callback_query_id, **kwargs: answers.append(str(kwargs.get("text"))),
    )
    return answers


def _capture_html(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    sent: list[str] = []
    monkeypatch.setattr(
        plugin_module,
        "send_rich_main_message",
        lambda bot_obj, chat_id, html, **kwargs: sent.append(html),
    )
    return sent


def _allow_plugin_scan(
    monkeypatch: pytest.MonkeyPatch, plugin: TrivyPlugin, *, accept: bool
) -> None:
    monkeypatch.setattr(plugin, "_authorized", lambda user_id, chat_type: True)
    monkeypatch.setattr(plugin, "_config", config())
    monkeypatch.setattr(plugin, "_queue", SimpleNamespace(submit=lambda job: accept))
    monkeypatch.setattr(runner, "local_image_ids", lambda *, limit: ["a" * 64])


def _callback(data: str, *, call_id: str, user_id: int = 123) -> CallbackQuery:
    return cast(
        CallbackQuery,
        SimpleNamespace(
            id=call_id,
            from_user=SimpleNamespace(id=user_id),
            message=SimpleNamespace(chat=SimpleNamespace(id=user_id, type="private")),
            data=data,
        ),
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("endpoint", "http://localhost:8090"),
        ("endpoint", "http://trivy-worker:8090@evil.invalid"),
        ("endpoint", "http://trivy-worker:8090/v1/scan"),
        ("endpoint", "https://trivy-worker:8090"),
        ("endpoint", "http://trivy-worker:8080"),
        ("token_file", "relative/secret"),
        ("history_file", "/path/../other"),
    ],
)
def test_config_rejects_unsafe_endpoints(field: str, value: str) -> None:
    values = config().model_dump()
    values[field] = value
    with pytest.raises(ValidationError):
        TrivyConfig.model_validate(values)


def test_disabled_by_default() -> None:
    assert TrivyConfig().enabled is False


def test_report_counts_and_provenance() -> None:
    raw = json.dumps(
        {
            "SchemaVersion": 2,
            "Results": [
                {
                    "Target": "alpine",
                    "Vulnerabilities": [
                        {
                            "VulnerabilityID": "CVE-2026-1234",
                            "PkgName": "openssl",
                            "Severity": "CRITICAL",
                            "FixedVersion": "3.0.1",
                        },
                        {
                            "VulnerabilityID": "CVE-2026-9999",
                            "PkgName": "libc",
                            "Severity": "HIGH",
                        },
                    ],
                }
            ],
        }
    ).encode()
    result = parse_report(
        raw,
        image_id="a" * 64,
        scanner_version="0.76.2",
        db_schema=2,
        db_updated_at="2026-11-11T12:00:00+00:00",
    )
    assert result.counts["CRITICAL"] == 1
    assert result.counts["HIGH"] == 1
    assert result.fixable == 1
    assert result.scanner_version == "0.76.2"
    assert result.vulnerability_ids == ("CVE-2026-1234", "CVE-2026-9999")


@pytest.mark.parametrize(
    "raw",
    [
        b"not-json",
        b"{}",
        b'{"Results":[]}',
        b'{"Results":[null]}',
        b'{"Results":[{"Vulnerabilities":{}}]}',
    ],
)
def test_invalid_reports_are_not_clean_results(raw: bytes) -> None:
    with pytest.raises(ScanError):
        parse_report(raw, image_id="a" * 64)


def test_local_image_selection_must_be_unambiguous(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "local_image_ids", lambda *, limit: ["a" * 64])
    assert runner.resolve_local_id("a" * 12, limit=5) == "a" * 64
    with pytest.raises(ScanError):
        runner.resolve_local_id("invalid", limit=5)
    monkeypatch.setattr(
        runner, "local_image_ids", lambda *, limit: ["a" * 64, "a" * 63 + "b"]
    )
    with pytest.raises(ScanError):
        runner.resolve_local_id("a" * 12, limit=5)


def test_http_scan_uses_only_local_image_id(monkeypatch: pytest.MonkeyPatch) -> None:
    image_id = "a" * 64
    monkeypatch.setattr(runner, "local_image_ids", lambda *, limit: [image_id])
    monkeypatch.setattr(runner, "_private_token", lambda path: "x" * 48)
    requests: list[Request] = []

    class Response(io.BytesIO):
        status = 200

    class Opener:
        def open(self, request: Request, timeout: int) -> Response:
            requests.append(request)
            assert timeout == 50
            return Response(
                json.dumps(
                    {
                        "image_id": f"sha256:{image_id}",
                        "scanner_version": "0.76.2",
                        "db_schema": 2,
                        "db_updated_at": datetime.now(UTC).isoformat(),
                        "report": {"Results": [{"Vulnerabilities": []}]},
                    }
                ).encode()
            )

    monkeypatch.setattr(runner, "_HTTP", Opener())
    summary = runner.scan_local_image(image_id, config())
    assert summary.image_id == image_id
    assert summary.scanner_version == "0.76.2"
    assert summary.counts["HIGH"] == 0
    assert len(requests) == 1
    assert requests[0].full_url == "http://trivy-worker:8090/v1/scan"
    payload = requests[0].data
    assert isinstance(payload, bytes)
    assert json.loads(payload) == {"image_id": f"sha256:{image_id}"}
    assert requests[0].get_header("Authorization") == "Bearer " + "x" * 48


def test_scan_rejects_changed_local_image_before_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "local_image_ids", lambda *, limit: ["b" * 64])
    with pytest.raises(ScanError):
        runner.scan_local_image("a" * 64, config())


def test_admin_and_private_session_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings.access_control, "allowed_admins_ids", [123])
    monkeypatch.setattr(
        plugin_module,
        "get_session_manager",
        lambda: SimpleNamespace(is_authenticated=lambda uid: uid == 123),
    )
    assert TrivyPlugin._authorized(123, "private") is True
    assert TrivyPlugin._authorized(123, "group") is False
    assert TrivyPlugin._authorized(456, "private") is False


def test_callback_owner_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = _new_bot()
    plugin = TrivyPlugin(bot)
    answers = _capture_answers(monkeypatch, bot)
    monkeypatch.setattr(plugin, "_authorized", lambda user_id, chat_type: True)
    plugin.handle_scan(_callback("trivy_scan:all:456", call_id="test"))
    assert answers == ["This button belongs to another user."]


def test_queue_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    from threading import Event

    started = Event()
    release = Event()

    def blocked_scan(
        image_id: str,
        cfg: TrivyConfig,
        *,
        cancel: Event | None = None,
    ) -> runner.ScanSummary:
        started.set()
        release.wait(timeout=2)
        return parse_report(b'{"Results":[{"Vulnerabilities":[]}]}', image_id=image_id)

    monkeypatch.setattr(runner, "scan_local_image", blocked_scan)
    received: list[str] = []
    queue = ScanQueue(
        config().model_copy(update={"max_queued_jobs": 1}),
        lambda job, status, summary: received.append(status),
    )
    job = ScanJob(chat_id=123, user_id=123, image_ids=("a" * 64,))
    try:
        assert queue.submit(job)
        assert started.wait(timeout=2)
        assert queue.submit(job)
        assert not queue.submit(job)
    finally:
        release.set()
        queue.cleanup()
    assert queue.submit(job) is False


def test_persistent_history_tracks_delta(tmp_path: Path) -> None:
    store = ScanHistory(str(tmp_path / "history.sqlite"))
    first = parse_report(
        json.dumps(
            {
                "Results": [
                    {
                        "Vulnerabilities": [
                            {"VulnerabilityID": "CVE-2026-0001", "Severity": "HIGH"},
                        ]
                    }
                ]
            }
        ).encode(),
        image_id="a" * 64,
    )
    assert store.append(first).previous is False
    second = parse_report(
        json.dumps(
            {
                "Results": [
                    {
                        "Vulnerabilities": [
                            {"VulnerabilityID": "CVE-2026-0001", "Severity": "HIGH"},
                            {
                                "VulnerabilityID": "CVE-2026-0002",
                                "Severity": "CRITICAL",
                            },
                        ]
                    }
                ]
            }
        ).encode(),
        image_id="a" * 64,
    )
    assert store.append(second).new_ids == ("CVE-2026-0002",)
    assert (
        ScanHistory(str(tmp_path / "history.sqlite")).recent()[0].counts["CRITICAL"]
        == 1
    )


def test_history_rejects_symlinks(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("not a database")
    target.chmod(0o600)
    alias = tmp_path / "alias"
    alias.symlink_to(target)
    with pytest.raises(HistoryError):
        ScanHistory(str(alias))


def test_stale_database_response_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    image_id = "a" * 64
    monkeypatch.setattr(runner, "local_image_ids", lambda *, limit: [image_id])
    monkeypatch.setattr(runner, "_private_token", lambda path: "x" * 48)

    class Response(io.BytesIO):
        status = 200

    class Opener:
        def open(self, request: object, timeout: int) -> Response:
            return Response(
                json.dumps(
                    {
                        "image_id": f"sha256:{image_id}",
                        "scanner_version": "0.76.2",
                        "db_schema": 2,
                        "db_updated_at": (
                            datetime.now(UTC) - timedelta(days=4)
                        ).isoformat(),
                        "report": {"Results": [{"Vulnerabilities": []}]},
                    }
                ).encode()
            )

    monkeypatch.setattr(runner, "_HTTP", Opener())
    with pytest.raises(ScanError, match="stale"):
        runner.scan_local_image(image_id, config())


def test_local_image_ids_are_truncated_not_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    images = [SimpleNamespace(id=f"sha256:{letter * 64}") for letter in "abc"]
    monkeypatch.setattr(runner, "docker_client_context", lambda: nullcontext(object()))
    monkeypatch.setattr(
        runner,
        "list_images_tolerant",
        lambda client, include_intermediate: images,
    )
    assert runner.local_image_ids(limit=2) == ["a" * 64, "b" * 64]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("max_db_age_hours", 49),
        ("timeout_seconds", 181),
        ("max_report_bytes", 2_097_153),
    ],
)
def test_config_does_not_promise_more_than_worker(field: str, value: int) -> None:
    values = config().model_dump()
    values[field] = value
    with pytest.raises(ValidationError):
        TrivyConfig.model_validate(values)


def test_register_adds_plugin_button_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = TeleBot("12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE")
    plugin = TrivyPlugin(bot)
    monkeypatch.setattr(plugin, "_config", config())
    registered: list[dict[str, object]] = []
    monkeypatch.setattr(
        bot,
        "register_message_handler",
        lambda handler, **kwargs: registered.append(kwargs),
    )
    monkeypatch.setattr(
        bot, "register_callback_query_handler", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        plugin_module,
        "ScanQueue",
        lambda cfg, publish: SimpleNamespace(cleanup=lambda: None),
    )
    plugin.register()
    assert any("regexp" in item for item in registered)
    assert any(item.get("commands") == ["trivy"] for item in registered)


def test_register_with_disabled_config_keeps_ui_responsive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = TeleBot("12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE")
    plugin = TrivyPlugin(bot)
    monkeypatch.setattr(
        plugin, "_config", config().model_copy(update={"enabled": False})
    )
    registered: list[dict[str, object]] = []
    monkeypatch.setattr(
        bot,
        "register_message_handler",
        lambda handler, **kwargs: registered.append(kwargs),
    )
    monkeypatch.setattr(
        bot, "register_callback_query_handler", lambda *args, **kwargs: None
    )
    plugin.register()
    assert plugin._queue is None
    assert plugin._history is None
    assert any(item.get("commands") == ["trivy"] for item in registered)


def _summary(*findings: tuple[str, str, str]) -> ScanSummary:
    counts = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNKNOWN": 0}
    for severity, _identifier, _package in findings:
        counts[severity] = counts[severity] + 1
    return ScanSummary(
        image_id="a" * 64,
        scanned_at="2026-11-21T14:00:00+00:00",
        scanner_version="0.76.2 <beta>",
        db_schema=2,
        db_updated_at="2026-11-21T12:00:00+00:00",
        counts=counts,
        fixable=1,
        findings=findings,
        trivy_schema=2,
        vulnerability_ids=tuple(item[1] for item in findings),
    )


def test_history_sections_distinguish_baseline_and_changes() -> None:
    baseline = render_report(_summary(), HistoryDelta(previous=False, new_ids=()))
    assert "Baseline" in baseline
    assert "First completed scan stored for this image." in baseline
    assert find_rich_html_issues(baseline) == []

    unchanged = render_report(_summary(), HistoryDelta(previous=True, new_ids=()))
    assert "No new vulnerability IDs since the previous scan." in unchanged
    assert "<ul>" not in unchanged

    without_history = render_report(_summary(), None)
    assert "Baseline" not in without_history
    assert "Changes" not in without_history


def test_scan_report_matches_rich_message_layout() -> None:
    html = render_report(
        _summary(
            ("HIGH", "CVE-2026-2<img>", "pkg"), ("CRITICAL", "CVE-2026-1", "libc")
        ),
        HistoryDelta(
            previous=True,
            new_ids=tuple(f"CVE-2026-{index:04d}" for index in range(10)),
        ),
    )
    assert find_rich_html_issues(html) == []
    assert html.startswith("<p><b>🛡️ Trivy scan</b></p>")
    assert html.rstrip().endswith("</footer>")
    assert "<code>aaaaaaaaaaaa</code>" in html
    assert "CVE-2026-2&lt;img&gt;" in html
    assert "0.76.2 &lt;beta&gt;" in html
    assert html.index("CVE-2026-1") < html.index("CVE-2026-2&lt;img&gt;")
    assert "With a known fix" in html
    assert "10 new vulnerability IDs." in html
    assert "2 more not shown." in html
    assert "21-11-2026 14:00:00" in html
    assert "not a clean image" not in html


def test_failed_scan_names_the_image_and_is_not_a_clean_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = TrivyPlugin(_new_bot())
    sent = _capture_html(monkeypatch)
    monkeypatch.setattr(plugin, "_authorized", lambda user_id, chat_type: True)
    plugin._publish(
        ScanJob(chat_id=123, user_id=123, image_ids=("b" * 64,)),
        "failed",
        None,
    )
    assert len(sent) == 1
    assert find_rich_html_issues(sent[0]) == []
    assert "Trivy scan failed" in sent[0]
    assert "bbbbbbbbbbbb" in sent[0]
    assert "not a clean image" in sent[0]
    assert "Critical" not in sent[0]
    assert render_failure("bbbbbbbbbbbb") == sent[0]


def test_history_screen_uses_a_severity_table() -> None:
    html = render_history([_summary()], listed_at="2026-11-21 14:05:00 UTC")
    assert find_rich_html_issues(html) == []
    assert html.startswith("<p><b>🛡️ Recent Trivy scans</b></p>")
    assert '<th align="right">Critical</th>' in html
    assert "<code>aaaaaaaaaaaa</code>" in html
    assert html.rstrip().endswith("</footer>")


def test_queue_reports_each_image_on_its_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def scan(
        image_id: str,
        cfg: TrivyConfig,
        *,
        cancel: Event | None = None,
    ) -> ScanSummary:
        del cfg, cancel
        if image_id.startswith("b"):
            raise ScanError("scanner failed")
        return _summary()

    published: list[tuple[tuple[str, ...], str]] = []
    finished = Event()

    def publish(job: ScanJob, status: str, summary: ScanSummary | None) -> None:
        del summary
        published.append((job.image_ids, status))
        if len(published) == 2:
            finished.set()

    monkeypatch.setattr(runner, "scan_local_image", scan)
    queue = ScanQueue(config(), publish)
    try:
        assert queue.submit(
            ScanJob(chat_id=123, user_id=123, image_ids=("a" * 64, "b" * 64))
        )
        assert finished.wait(timeout=2)
    finally:
        queue.cleanup()
    assert published == [(("a" * 64,), "complete"), (("b" * 64,), "failed")]


def _message(user_id: int, chat_id: int, chat_type: str) -> Message:
    return cast(
        Message,
        SimpleNamespace(
            from_user=SimpleNamespace(id=user_id),
            chat=SimpleNamespace(id=chat_id, type=chat_type),
        ),
    )


def _capture_replies(
    monkeypatch: pytest.MonkeyPatch, bot: TeleBot
) -> list[dict[str, object]]:
    sent: list[dict[str, object]] = []
    monkeypatch.setattr(bot, "send_chat_action", lambda *args, **kwargs: None)

    def capture(bot_obj: TeleBot, chat_id: int, html: str, **kwargs: object) -> None:
        del bot_obj, chat_id
        sent.append({"html": html, "reply_markup": kwargs.get("reply_markup")})

    monkeypatch.setattr(plugin_module, "send_rich_main_message", capture)
    return sent


def test_menu_uses_emoji_title_and_inline_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = TeleBot("12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE")
    plugin = TrivyPlugin(bot)
    sent = _capture_replies(monkeypatch, bot)
    monkeypatch.setattr(settings.access_control, "allowed_admins_ids", [123])
    monkeypatch.setattr(
        plugin_module,
        "get_session_manager",
        lambda: SimpleNamespace(is_authenticated=lambda uid: uid == 123),
    )
    monkeypatch.setattr(plugin, "_config", config())
    monkeypatch.setattr(plugin, "_queue", SimpleNamespace(submit=lambda job: True))
    monkeypatch.setattr(
        plugin_module,
        "local_image_ids",
        lambda *, limit: ["a" * 64, "b" * 64],
    )
    plugin.handle_menu(_message(123, 123, "private"))
    assert len(sent) == 1
    html = sent[0]["html"]
    assert isinstance(html, str)
    assert find_rich_html_issues(html) == []
    assert html.startswith("<p><b>🛡️ Trivy scans</b></p>")
    assert "2 verified local images (limit 5)." in html
    markup = cast(InlineKeyboardMarkup, sent[0]["reply_markup"])
    assert markup is not None
    rows = markup.inline_keyboard
    assert len(rows[0]) == 2
    assert rows[0][0].callback_data == "trivy_scan:" + "a" * 12 + ":123"
    assert rows[0][0].text.endswith("a" * 12)
    assert "🔍" in rows[0][0].text
    assert len(rows[-1]) == 1
    assert rows[-1][0].text.endswith("Scan all")
    assert rows[-1][0].callback_data == "trivy_scan:all:123"
    assert rows[-1][0].style == "primary"


def test_history_storage_failure_withholds_findings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin = TrivyPlugin(_new_bot())
    sent = _capture_html(monkeypatch)
    monkeypatch.setattr(plugin, "_authorized", lambda user_id, chat_type: True)

    def reject(summary: ScanSummary) -> HistoryDelta:
        del summary
        raise HistoryError("unavailable")

    plugin._history = cast(ScanHistory, SimpleNamespace(append=reject))
    plugin._publish(
        ScanJob(chat_id=123, user_id=123, image_ids=("a" * 64,)),
        "complete",
        _summary(("CRITICAL", "CVE-2026-9", "openssl")),
    )
    assert len(sent) == 1
    assert "Result withheld" in sent[0]
    assert "aaaaaaaaaaaa" in sent[0]
    assert "CVE-2026-9" not in sent[0]
    assert find_rich_html_issues(sent[0]) == []


def _admin_menu(
    monkeypatch: pytest.MonkeyPatch, *, authenticated: bool = True
) -> tuple[TrivyPlugin, list[dict[str, object]]]:
    bot = TeleBot("12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE")
    plugin = TrivyPlugin(bot)
    sent = _capture_replies(monkeypatch, bot)
    monkeypatch.setattr(settings.access_control, "allowed_admins_ids", [123])
    monkeypatch.setattr(
        plugin_module,
        "get_session_manager",
        lambda: SimpleNamespace(is_authenticated=lambda uid: authenticated),
    )
    plugin._config = config()
    plugin._queue = cast(ScanQueue, SimpleNamespace(submit=lambda job: True))
    return plugin, sent


def test_menu_notices_cover_disabled_discovery_and_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin, sent = _admin_menu(monkeypatch, authenticated=False)
    plugin.handle_menu(_message(123, 123, "private"))
    assert isinstance(sent[-1]["html"], str)
    assert "2FA required" in sent[-1]["html"]

    plugin, sent = _admin_menu(monkeypatch)
    plugin._queue = None
    plugin.handle_menu(_message(123, 123, "private"))
    assert "Trivy is off" in str(sent[-1]["html"])

    plugin, sent = _admin_menu(monkeypatch)

    def fail_discovery(*, limit: int) -> list[str]:
        del limit
        raise ScanError("docker down")

    monkeypatch.setattr(plugin_module, "local_image_ids", fail_discovery)
    plugin.handle_menu(_message(123, 123, "private"))
    assert "Docker image discovery failed." in str(sent[-1]["html"])

    def empty(*, limit: int) -> list[str]:
        del limit
        return []

    monkeypatch.setattr(plugin_module, "local_image_ids", empty)
    plugin.handle_menu(_message(123, 123, "private"))
    assert "No local images" in str(sent[-1]["html"])

    plugin.handle_menu(_message(999, 999, "private"))
    assert "Access denied" in str(sent[-1]["html"])
    assert find_rich_html_issues(str(sent[-1]["html"])) == []


def test_history_notices_for_missing_and_empty_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin, sent = _admin_menu(monkeypatch)
    plugin.handle_history(_message(123, 123, "private"))
    assert "History is off" in str(sent[-1]["html"])

    plugin._history = cast(ScanHistory, SimpleNamespace(recent=lambda: []))
    plugin.handle_history(_message(123, 123, "private"))
    assert "No scans yet" in str(sent[-1]["html"])

    def unavailable() -> list[ScanSummary]:
        raise HistoryError("locked")

    plugin._history = cast(ScanHistory, SimpleNamespace(recent=unavailable))
    plugin.handle_history(_message(123, 123, "private"))
    assert "History unavailable" in str(sent[-1]["html"])
    assert find_rich_html_issues(str(sent[-1]["html"])) == []


def test_scan_button_explains_a_full_queue(monkeypatch: pytest.MonkeyPatch) -> None:
    bot = _new_bot()
    plugin = TrivyPlugin(bot)
    answers = _capture_answers(monkeypatch, bot)
    _allow_plugin_scan(monkeypatch, plugin, accept=False)
    plugin.handle_scan(_callback("trivy_scan:" + "a" * 12 + ":123", call_id="full"))
    assert answers == ["The scan queue is full."]


def test_group_admin_is_sent_to_a_private_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = TeleBot("12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE")
    plugin = TrivyPlugin(bot)
    sent = _capture_replies(monkeypatch, bot)
    monkeypatch.setattr(settings.access_control, "allowed_admins_ids", [123])
    monkeypatch.setattr(
        plugin_module,
        "get_session_manager",
        lambda: SimpleNamespace(is_authenticated=lambda uid: True),
    )
    plugin.handle_menu(_message(123, -100, "group"))
    html = sent[0]["html"]
    assert isinstance(html, str)
    assert "Private chat" in html
    assert "Access denied" not in html
    assert find_rich_html_issues(html) == []


def test_queued_notice_pluralizes_several_scans() -> None:
    html = render_queued(2)
    assert "2 local image scans queued." in html
    assert "scan(s)" not in html
    assert find_rich_html_issues(html) == []


def test_queued_confirmation_uses_a_real_plural(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = _new_bot()
    plugin = TrivyPlugin(bot)
    sent = _capture_replies(monkeypatch, bot)
    answers = _capture_answers(monkeypatch, bot)
    _allow_plugin_scan(monkeypatch, plugin, accept=True)
    call = _callback("trivy_scan:" + "a" * 12 + ":123", call_id="queued")
    plugin.handle_scan(call)
    assert answers == ["Scan queued"]
    html = sent[0]["html"]
    assert isinstance(html, str)
    assert "1 local image scan queued." in html
    assert "scan(s)" not in html
    assert find_rich_html_issues(html) == []
