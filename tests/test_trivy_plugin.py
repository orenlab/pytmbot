"""Regression checks for the optional Trivy integration; no scanner required."""

from __future__ import annotations

import hashlib
import json
import socket
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from pydantic import ValidationError
from telebot import TeleBot
from telebot.types import CallbackQuery

from pytmbot.globals import settings
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
        scanner_sha256="0" * 64,
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
        settings.access_control,
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

    def blocked_scan(
        image_id: str, cfg: TrivyConfig, *, cancel: Event | None = None,
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

def test_scanner_output_is_bounded_without_shell(tmp_path: Path) -> None:
    argv = [sys.executable, "-c", "import sys;sys.stdout.write('x'*1024)"]
    with pytest.raises(ScanError, match="size limit"):
        runner._bounded_stdout(
            argv, env={"PATH": "/usr/bin:/bin"}, cwd=str(tmp_path),
            timeout_seconds=1, max_bytes=32,
        )


def test_scanner_nonzero_is_not_a_clean_result(tmp_path: Path) -> None:
    with pytest.raises(ScanError, match="Trivy failed"):
        runner._bounded_stdout(
            [sys.executable, "-c", "raise SystemExit(7)"],
            env={"PATH": "/usr/bin:/bin"}, cwd=str(tmp_path),
            timeout_seconds=1, max_bytes=32,
        )


def test_scanner_success_returns_bounded_output(tmp_path: Path) -> None:
    raw = runner._bounded_stdout(
        [sys.executable, "-c", "print('ok')"],
        env={"PATH": "/usr/bin:/bin"}, cwd=str(tmp_path),
        timeout_seconds=1, max_bytes=32,
    )
    assert raw == b"ok\n"


def test_pinned_scanner_hash(tmp_path: Path) -> None:
    binary = tmp_path / "trivy"
    binary.write_bytes(b"known-binary")
    expected = hashlib.sha256(b"known-binary").hexdigest()
    runner.verify_scanner_binary(binary, expected)
    with pytest.raises(ScanError, match="mismatch"):
        runner.verify_scanner_binary(binary, "0" * 64)


def test_db_freshness_and_metadata_provenance(tmp_path: Path) -> None:
    db = tmp_path / "db"
    db.mkdir()
    (db / "trivy.db").write_bytes(b"dummy")
    now = datetime.now(UTC)
    metadata = db / "metadata.json"
    metadata.write_text(json.dumps({
        "Version": 2,
        "UpdatedAt": now.isoformat(),
        "NextUpdate": (now + timedelta(hours=4)).isoformat(),
        "DownloadedAt": now.isoformat(),
    }))
    info = runner.read_database_metadata(tmp_path, max_age_hours=48)
    assert info.schema == 2
    assert info.updated_at
    metadata.write_text(json.dumps({
        "Version": 2,
        "UpdatedAt": (now - timedelta(days=4)).isoformat(),
    }))
    with pytest.raises(ScanError, match="stale"):
        runner.read_database_metadata(tmp_path, max_age_hours=48)


def test_db_metadata_missing_or_invalid_is_not_accepted(tmp_path: Path) -> None:
    with pytest.raises(ScanError):
        runner.read_database_metadata(tmp_path, max_age_hours=48)
    (tmp_path / "db").mkdir()
    (tmp_path / "db" / "trivy.db").write_bytes(b"dummy")
    (tmp_path / "db" / "metadata.json").write_text('{"UpdatedAt":"unknown"}')
    with pytest.raises(ScanError):
        runner.read_database_metadata(tmp_path, max_age_hours=48)


def test_config_rejects_missing_or_invalid_scanner_digest() -> None:
    raw = config().model_dump()
    raw.pop("scanner_sha256")
    with pytest.raises(ValidationError):
        TrivyConfig.model_validate(raw)
    raw["scanner_sha256"] = "not-a-sha256"
    with pytest.raises(ValidationError):
        TrivyConfig.model_validate(raw)


def test_scanner_cancellation_terminates_child(tmp_path: Path) -> None:
    from threading import Event, Thread
    from time import sleep

    cancel = Event()
    result: list[Exception] = []

    def invoke() -> None:
        try:
            runner._bounded_stdout(
                [sys.executable, "-c", "import time;time.sleep(30)"],
                env={"PATH": "/usr/bin:/bin"},
                cwd=str(tmp_path), timeout_seconds=35,
                max_bytes=256, cancel=cancel,
            )
        except ScanError as exc:
            result.append(exc)

    thread = Thread(target=invoke)
    thread.start()
    sleep(0.15)
    cancel.set()
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert result and "cancelled" in str(result[0])


def test_scan_uses_only_pinned_local_image_and_bounded_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    binary = tmp_path / "trivy"
    binary.write_bytes(b"verified-trivy")
    binary.chmod(0o700)
    cache = tmp_path / "cache"
    (cache / "db").mkdir(parents=True)
    (cache / "db" / "trivy.db").write_bytes(b"dummy")
    (cache / "db" / "metadata.json").write_text(json.dumps({
        "Version": 2,
        "UpdatedAt": datetime.now(UTC).isoformat(),
    }))
    docker_socket = tmp_path / "docker.sock"
    image_id = "a" * 64
    monkeypatch.setattr(runner, "local_image_ids", lambda *, limit: [image_id])
    observed: list[str] = []

    def fake_scan(
        argv: list[str], *, env: dict[str, str], cwd: str,
        timeout_seconds: int, max_bytes: int, cancel: object = None,
    ) -> bytes:
        observed.extend(argv)
        assert "DOCKER_HOST" not in env
        assert "HOME" in env
        assert cwd == "/"
        return b'{"Results":[{"Vulnerabilities":[]}]}'

    monkeypatch.setattr(runner, "_bounded_stdout", fake_scan)
    cfg = config().model_copy(update={
        "executable": str(binary),
        "docker_host": f"unix://{docker_socket}",
        "cache_dir": str(cache),
        "scanner_sha256": hashlib.sha256(b"verified-trivy").hexdigest(),
        "max_image_size_mb": 256,
    })
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
        server.bind(str(docker_socket))
        report = runner.scan_local_image(image_id, cfg)
    assert report.image_id == image_id
    assert report.db_schema == 2
    assert report.scanner_sha256 == cfg.scanner_sha256
    assert observed[-1] == "sha256:" + image_id
    assert observed[observed.index("--image-src") + 1] == "docker"
    assert observed[observed.index("--parallel") + 1] == "1"
    assert observed[observed.index("--max-image-size") + 1] == "256MB"
    assert "--offline-scan" in observed
    assert "--skip-db-update" in observed
    assert observed[observed.index("--config") + 1] == "/dev/null"
    assert observed[observed.index("--ignorefile") + 1] == "/dev/null"
    assert observed[observed.index("--exit-code") + 1] == "0"
