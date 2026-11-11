"""Regression checks for the optional Trivy integration; no scanner required."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import ValidationError
from telebot import TeleBot
from telebot.types import CallbackQuery, Message

from pytmbot.models.settings_model import TrivyConfig
from pytmbot.plugins.trivy import plugin as plugin_module
from pytmbot.plugins.trivy import runner
from pytmbot.plugins.trivy.plugin import TrivyPlugin
from pytmbot.plugins.trivy.runner import ScanError, ScanJob, ScanQueue, parse_report


def config() -> TrivyConfig:
    return TrivyConfig(
        enabled=True,
        executable="/opt/trivy/trivy",
        docker_host="unix:///run/trivy/docker.sock",
        cache_dir="/var/cache/trivy",
        timeout_seconds=30,
        max_images=5,
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("executable", "trivy"),
        ("cache_dir", "cache"),
        ("docker_host", "tcp://127.0.0.1:2375"),
        ("docker_host", "unix:///run/../docker.sock"),
    ],
)
def test_config_rejects_unsafe_paths(field: str, value: str) -> None:
    data = config().model_dump()
    data[field] = value
    with pytest.raises(ValidationError):
        TrivyConfig.model_validate(data)


def test_disabled_by_default() -> None:
    data = config().model_dump(exclude={"enabled"})
    assert TrivyConfig.model_validate(data).enabled is False


def test_report_counts_and_fixed_versions() -> None:
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
    result = parse_report(raw, image_id="a" * 64)
    assert result.counts["CRITICAL"] == 1
    assert result.counts["HIGH"] == 1
    assert result.counts["LOW"] == 0
    assert result.fixable == 1
    assert result.findings[0] == ("CRITICAL", "CVE-2026-1234", "openssl")


@pytest.mark.parametrize(
    "raw",
    [b"not-json", b"{}", b'{"Results":[]}', b'{"Results":[null]}',
     b'{"Results":[{"Vulnerabilities":{}}]}'],
)
def test_invalid_or_inconclusive_reports_are_not_zero_findings(raw: bytes) -> None:
    with pytest.raises(ScanError):
        parse_report(raw, image_id="a" * 64)


def test_local_image_prefix_must_be_unique(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "local_image_ids", lambda *, limit: ["a" * 64])
    assert runner.resolve_local_id("a" * 12, limit=5) == "a" * 64
    with pytest.raises(ScanError):
        runner.resolve_local_id("not-an-id", limit=5)
    monkeypatch.setattr(runner, "local_image_ids", lambda *, limit: ["a" * 64, "a" * 63 + "b"])
    with pytest.raises(ScanError):
        runner.resolve_local_id("a" * 12, limit=5)


def test_scanner_rejects_unverified_id_before_subprocess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(runner, "local_image_ids", lambda *, limit: ["b" * 64])
    with pytest.raises(ScanError):
        runner.scan_local_image("a" * 64, config())


def test_admin_and_private_session_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        plugin_module.settings.access_control,
        "allowed_admins_ids",
        [123],
    )
    monkeypatch.setattr(
        plugin_module, "get_session_manager",
        lambda: SimpleNamespace(is_authenticated=lambda uid: uid == 123),
    )
    assert TrivyPlugin._authorized(123, "private") is True
    assert TrivyPlugin._authorized(123, "group") is False
    assert TrivyPlugin._authorized(456, "private") is False


def test_callback_owner_mismatch_does_not_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot = TeleBot("12345678:ABCDEFGHIJKLMNOPQRSTUVWXYZABCDE")
    plugin = TrivyPlugin(bot)
    answers: list[str] = []
    monkeypatch.setattr(
        bot, "answer_callback_query",
        lambda callback_query_id, **kwargs: answers.append(str(kwargs.get("text"))),
    )
    monkeypatch.setattr(
        plugin, "_authorized", lambda user_id, chat_type: True
    )
    callback = cast(CallbackQuery, SimpleNamespace(
        id="test", from_user=SimpleNamespace(id=123),
        message=SimpleNamespace(chat=SimpleNamespace(id=123, type="private")),
        data="trivy_scan:all:456",
    ))
    plugin.handle_scan(callback)
    assert answers == ["This scan button is not yours."]


def test_queue_is_bounded_and_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    from threading import Event

    started = Event()
    release = Event()

    def blocked_scan(image_id: str, cfg: TrivyConfig) -> runner.ScanSummary:
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
