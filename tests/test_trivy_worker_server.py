"""Unit tests for the isolated Trivy worker HTTP contract."""

from __future__ import annotations

import importlib.util
import io
import json
import logging
import os
import threading
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

_MODULE_PATH = Path(__file__).resolve().parents[1] / "trivy-worker" / "server.py"
_SPEC = importlib.util.spec_from_file_location(
    "pytmbot_trivy_worker_server", _MODULE_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
worker = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(worker)

_IMAGE_ID = "sha256:" + "a" * 64


class _FakeRequestHandler:
    def __init__(self, body: bytes, *, content_length: int | None = None) -> None:
        self.headers = {
            "Content-Length": str(
                len(body) if content_length is None else content_length
            )
        }
        self.rfile = io.BytesIO(body)


def _db_info(updated_at: str, *, version: object = 2) -> dict[str, object]:
    return {
        "Version": "0.76.2",
        "VulnerabilityDB": {"Version": version, "UpdatedAt": updated_at},
    }


def test_secret_file_is_bounded(tmp_path: Path) -> None:
    secret = tmp_path / "token"
    secret.write_text("x" * 31, encoding="utf-8")
    with pytest.raises(ValueError):
        worker.secret_file(str(secret))

    secret.write_text("x" * 32, encoding="utf-8")
    assert worker.secret_file(str(secret)) == "x" * 32

    with pytest.raises(ValueError):
        worker.secret_file(str(tmp_path / "missing"))


def test_parse_scan_request_accepts_only_exact_shape() -> None:
    valid = json.dumps({"image_id": _IMAGE_ID}).encode()
    assert worker._parse_scan_request(_FakeRequestHandler(valid)) == _IMAGE_ID

    invalid_bodies = (
        b"",
        b"{}",
        b'{"image_id": "sha256:abc"}',
        b'{"image_id": "a" * 64}',
        b'{"image_id": "sha256:' + b"a" * 64 + b'", "command": "id"}',
        b'{"image_id": 1}',
        b"[]",
    )
    for body in invalid_bodies:
        with pytest.raises(ValueError):
            worker._parse_scan_request(_FakeRequestHandler(body))

    with pytest.raises(ValueError):
        worker._parse_scan_request(_FakeRequestHandler(valid, content_length=0))
    with pytest.raises(ValueError):
        worker._parse_scan_request(_FakeRequestHandler(valid, content_length=129))
    with pytest.raises(ValueError):
        worker._parse_scan_request(_FakeRequestHandler(valid, content_length=-1))


def test_scanner_args_are_fixed_and_local_only() -> None:
    args = worker._scanner_args(_IMAGE_ID)
    assert args[0] == "trivy"
    assert args[-1] == _IMAGE_ID
    for expected in (
        "--server",
        "--image-src",
        "--docker-host",
        "--format",
        "--scanners",
        "--offline-scan",
        "--config",
        "--ignorefile",
        "--max-image-size",
        "--parallel",
        "--skip-check-update",
    ):
        assert expected in args
    assert "--download-db-only" not in args
    assert "--reset" not in args
    assert "--ignore-unfixed" not in args


def test_database_info_accepts_fresh_and_rejects_bad_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime.now(UTC)
    monkeypatch.setattr(
        worker,
        "_get_json",
        lambda url, limit=8192: _db_info(now.isoformat()),
    )
    info = worker.database_info()
    assert info["db_schema"] == 2
    assert info["scanner_version"] == "0.76.2"

    monkeypatch.setattr(
        worker,
        "_get_json",
        lambda url, limit=8192: _db_info((now - timedelta(hours=49)).isoformat()),
    )
    with pytest.raises(worker.ScanFailure, match="stale"):
        worker.database_info()

    monkeypatch.setattr(
        worker,
        "_get_json",
        lambda url, limit=8192: _db_info((now + timedelta(minutes=10)).isoformat()),
    )
    with pytest.raises(worker.ScanFailure, match="stale"):
        worker.database_info()

    monkeypatch.setattr(
        worker,
        "_get_json",
        lambda url, limit=8192: _db_info(now.isoformat(), version="2"),
    )
    with pytest.raises(worker.ScanFailure, match="metadata"):
        worker.database_info()


def test_verified_image_returns_canonical_id_and_rejects_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(worker, "_get_json", lambda url, limit=1: {"Id": _IMAGE_ID})
    assert worker.verified_image(_IMAGE_ID) == _IMAGE_ID

    monkeypatch.setattr(
        worker, "_get_json", lambda url, limit=1: {"Id": "sha256:" + "b" * 64}
    )
    with pytest.raises(worker.ScanFailure):
        worker.verified_image(_IMAGE_ID)

    with pytest.raises(worker.ScanFailure):
        worker.verified_image("sha256:not-hex")


def test_read_output_enforces_size_limit(tmp_path: Path) -> None:
    report = tmp_path / "report.json"
    report.write_bytes(b"x" * (worker.MAX_REPORT_BYTES + 1))
    with report.open("rb") as stream:
        proc = SimpleNamespace(stdout=stream)
        with pytest.raises(worker.ScanFailure, match="size limit"):
            worker._read_output(proc, time.monotonic() + 5)


def test_read_output_times_out_without_data() -> None:
    read_fd, write_fd = os.pipe()
    stream = os.fdopen(read_fd, "rb")
    try:
        proc = SimpleNamespace(stdout=stream)
        with pytest.raises(worker.ScanFailure, match="timed out"):
            worker._read_output(proc, time.monotonic() + 0.01)
    finally:
        os.close(write_fd)
        stream.close()


def test_scan_result_uses_docker_canonical_id(monkeypatch: pytest.MonkeyPatch) -> None:
    canonical = "sha256:" + "c" * 64
    scanned: list[str] = []
    monkeypatch.setattr(worker, "verified_image", lambda image_id: canonical)
    monkeypatch.setattr(
        worker,
        "database_info",
        lambda: {
            "scanner_version": "0.76.2",
            "db_schema": 2,
            "db_updated_at": datetime.now(UTC).isoformat(),
        },
    )

    def fake_scan(image_id: str) -> dict[str, Any]:
        scanned.append(image_id)
        return {"Results": [{"Vulnerabilities": []}]}

    monkeypatch.setattr(worker, "bounded_scan", fake_scan)
    result = worker._scan_result(_IMAGE_ID)
    assert scanned == [canonical]
    assert result["image_id"] == canonical


def test_non_ascii_authorization_is_rejected_without_crashing() -> None:
    handler = SimpleNamespace(
        headers={"Authorization": "Bearer \xfc"},
        server=SimpleNamespace(api_token="t" * 32),
    )
    assert worker.Handler._authorized(cast(Any, handler)) is False


def test_stop_scanner_does_not_mask_scan_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StuckProcess:
        pid = 12345
        stdout = None

        def poll(self) -> None:
            return None

        def wait(self, timeout: int) -> None:
            raise worker.subprocess.TimeoutExpired("trivy", timeout)

    monkeypatch.setattr(worker.os, "killpg", lambda pid, sig: None)
    worker._stop_scanner(cast(Any, StuckProcess()))


class _WorkerServer:
    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._thread: threading.Thread | None = None
        self._httpd = worker.Server(("127.0.0.1", 0), worker.Handler)
        self._httpd.api_token = "t" * 32
        monkeypatch.setattr(
            worker,
            "database_info",
            lambda: {
                "scanner_version": "0.76.2",
                "db_schema": 2,
                "db_updated_at": datetime.now(UTC).isoformat(),
            },
        )

    def __enter__(self) -> _WorkerServer:
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)

    @property
    def port(self) -> int:
        return int(self._httpd.server_address[1])

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        token: bool = False,
        body: bytes | None = None,
    ) -> tuple[int, dict[str, object] | None]:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = "Bearer " + "t" * 32
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())


def test_http_auth_health_and_scan_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker, "_scan_result", lambda image_id: {"image_id": image_id})
    with _WorkerServer(monkeypatch) as server:
        assert server.request("/healthz")[0] == 200
        assert server.request("/v1/info")[0] == 401
        assert server.request("/v1/info", token=True)[0] == 200
        assert server.request("/v1/scan", token=True)[0] == 404
        assert (
            server.request("/v1/scan", method="POST", token=True, body=b"{}")[0] == 400
        )
        status, result = server.request(
            "/v1/scan",
            method="POST",
            token=True,
            body=json.dumps({"image_id": _IMAGE_ID}).encode(),
        )
        assert status == 200
        assert result == {"image_id": _IMAGE_ID}


def test_log_level_parsing() -> None:
    assert worker._log_level("debug") == logging.DEBUG
    assert worker._log_level("WARNING") == logging.WARNING
    assert worker._log_level("not-a-level") == logging.INFO


def test_json_formatter_emits_structured_line() -> None:
    record = logging.LogRecord(
        name="pytmbot.trivy.worker",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="bot.plugins.trivy.worker.scan.complete",
        args=(),
        exc_info=None,
    )
    record.__dict__["context"] = {"image": "abcdef123456", "duration_ms": 12}
    payload = json.loads(worker._JsonFormatter().format(record))
    assert payload["level"] == "INFO"
    assert payload["module"] == record.module
    assert payload["msg"] == "bot.plugins.trivy.worker.scan.complete"
    assert payload["image"] == "abcdef123456"
    assert payload["duration_ms"] == 12
    assert str(payload["ts"]).endswith("Z")


def test_scan_failure_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(worker, "verified_image", lambda image_id: _IMAGE_ID)

    def fail() -> dict[str, str | int]:
        raise worker.ScanFailure("stale database")

    monkeypatch.setattr(worker, "database_info", fail)
    with caplog.at_level(logging.WARNING, logger="pytmbot.trivy.worker"):
        with pytest.raises(worker.ScanFailure):
            worker._scan_result(_IMAGE_ID)
    assert any(
        record.msg == "bot.plugins.trivy.worker.scan.fail" for record in caplog.records
    )
