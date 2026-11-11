"""Private HTTP adapter for the official Trivy client/server containers.

The API accepts only immutable local image IDs. It does not accept arbitrary
Trivy commands, image names, paths, registry URLs, flags, or Docker operations.
"""

from __future__ import annotations

import hmac
import json
import os
import re
import select
import signal
import subprocess
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, cast
from threading import BoundedSemaphore
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import ProxyHandler, Request, build_opener

TRIVY_SERVER = "http://trivy-db:4954"
DOCKER_API = "http://trivy-docker-proxy:2375"
DOCKER_HOST = "tcp://trivy-docker-proxy:2375"
IMAGE_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
HTTP = build_opener(ProxyHandler({}))
GUARD = BoundedSemaphore(value=1)
MAX_REPORT_BYTES = 2_097_152
MAX_IMAGE_MB = 1024
TIMEOUT = 180


class ScanFailure(Exception):
    """A scan failed and cannot be represented as a clean vulnerability result."""


def secret_file(path: str) -> str:
    value = Path(path).read_text(encoding="utf-8").strip()
    if len(value) < 32 or len(value) > 256:
        raise ValueError("Trivy worker token must contain 32-256 characters")
    return value


def token() -> str:
    return secret_file(os.environ.get(
        "TRIVY_WORKER_TOKEN_FILE", "/run/secrets/trivy_worker_token"
    ))


def _get_json(url: str, *, limit: int = 8192) -> dict[str, Any]:
    try:
        with HTTP.open(Request(
            url, method="GET",
            headers={"Trivy-Token": secret_file(
                os.environ.get(
                    "TRIVY_SERVER_TOKEN_FILE", "/run/secrets/trivy_server_token"
                )
            )} if url.startswith(TRIVY_SERVER + "/") else {},
        ), timeout=5) as response:
            if response.status != 200:
                raise ScanFailure("Trivy dependency returned an HTTP error")
            raw = response.read(limit + 1)
        if len(raw) > limit:
            raise ScanFailure("Trivy dependency response exceeded limit")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ScanFailure("Invalid Trivy dependency response")
        return result
    except (HTTPError, URLError, OSError, ValueError) as exc:
        raise ScanFailure("Trivy dependency is unavailable") from exc


def verified_image(image_id: str) -> None:
    if not IMAGE_RE.fullmatch(image_id):
        raise ScanFailure("Invalid immutable local image ID")
    path = quote(image_id, safe=":")
    obj = _get_json(f"{DOCKER_API}/images/{path}/json", limit=262144)
    if obj.get("Id") != image_id:
        raise ScanFailure("Image no longer matches requested local ID")


def database_info(*, max_age_hours: int = 48) -> dict[str, str | int]:
    info = _get_json(f"{TRIVY_SERVER}/version")
    db = info.get("VulnerabilityDB")
    if not isinstance(db, dict):
        raise ScanFailure("Trivy vulnerability database is unavailable")
    version = db.get("Version")
    updated = db.get("UpdatedAt")
    if type(version) is not int or not isinstance(updated, str):
        raise ScanFailure("Trivy vulnerability database metadata is invalid")
    try:
        parsed = datetime.fromisoformat(updated.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("Naive time")
        age = datetime.now(UTC) - parsed.astimezone(UTC)
    except ValueError as exc:
        raise ScanFailure("Trivy vulnerability database timestamp is invalid") from exc
    if age < -timedelta(minutes=5) or age > timedelta(hours=max_age_hours):
        raise ScanFailure("Trivy vulnerability database is stale")
    return {
        "scanner_version": str(info.get("Version", ""))[:48],
        "db_schema": version,
        "db_updated_at": parsed.astimezone(UTC).isoformat(),
    }


def _scanner_args(image_id: str) -> list[str]:
    return [
        "trivy", "image", "--server", TRIVY_SERVER, "--image-src", "docker",
        "--docker-host", DOCKER_HOST, "--format", "json", "--scanners", "vuln",
        "--quiet", "--no-progress", "--offline-scan",
        "--config", "/dev/null", "--ignorefile", "/dev/null",
        "--exit-code", "0", "--parallel", "1",
        "--max-image-size", f"{MAX_IMAGE_MB}MB",
        "--skip-check-update", "--disable-telemetry",
        "--timeout", f"{TIMEOUT}s", image_id,
    ]


def _scanner_env() -> dict[str, str]:
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/tmp",
        "TMPDIR": "/tmp",
        "LANG": "C",
        "DOCKER_CONFIG": "/tmp/no-docker-credentials",
        "TRIVY_TOKEN": secret_file(
            os.environ.get("TRIVY_SERVER_TOKEN_FILE", "/run/secrets/trivy_server_token")
        ),
        "TRIVY_DISABLE_TELEMETRY": "true",
    }


def _read_output(proc: subprocess.Popen[bytes], deadline: float) -> bytes:
    stream = proc.stdout
    if stream is None:
        raise ScanFailure("Trivy scanner stdout is unavailable")
    fd = stream.fileno()
    chunks: list[bytes] = []
    consumed = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ScanFailure("Trivy scanner timed out")
        ready, _, _ = select.select([fd], [], [], min(1.0, remaining))
        if not ready:
            continue
        data = os.read(fd, min(65536, MAX_REPORT_BYTES - consumed + 1))
        if not data:
            break
        consumed += len(data)
        if consumed > MAX_REPORT_BYTES:
            raise ScanFailure("Trivy report exceeded size limit")
        chunks.append(data)
    return b"".join(chunks)


def _stop_scanner(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=5)
    if proc.stdout is not None:
        proc.stdout.close()


def bounded_scan(image_id: str) -> dict[str, Any]:
    """Run a single Docker-only image scan with bounded time and output."""
    try:
        proc = subprocess.Popen(
            _scanner_args(image_id),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=_scanner_env(), cwd="/",
            start_new_session=True,
        )
    except OSError as exc:
        raise ScanFailure("Trivy scanner could not start") from exc
    deadline = time.monotonic() + TIMEOUT + 10
    try:
        raw = _read_output(proc, deadline)
        if proc.wait(timeout=max(0.01, deadline - time.monotonic())) != 0:
            raise ScanFailure("Trivy scanner returned an error")
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise ScanFailure("Trivy report was incomplete")
        targets = result.get("Results")
        if not isinstance(targets, list) or not targets:
            raise ScanFailure("Trivy report was incomplete")
        return result
    except (ValueError, subprocess.TimeoutExpired) as exc:
        raise ScanFailure("Trivy did not produce a valid report") from exc
    finally:
        _stop_scanner(proc)


def _parse_scan_request(handler: BaseHTTPRequestHandler) -> str:
    length = int(handler.headers.get("Content-Length", "0"))
    if not 1 <= length <= 128:
        raise ValueError("Invalid request length")
    obj = json.loads(handler.rfile.read(length))
    if not isinstance(obj, dict) or set(obj) != {"image_id"}:
        raise ValueError("Unexpected scan request")
    image_id = obj["image_id"]
    if not isinstance(image_id, str) or not IMAGE_RE.fullmatch(image_id):
        raise ValueError("Invalid immutable local image ID")
    return image_id


def _scan_result(image_id: str) -> dict[str, object]:
    verified_image(image_id)
    info = database_info()
    report = bounded_scan(image_id)
    verified_image(image_id)
    return {"image_id": image_id, **info, "report": report}


class Handler(BaseHTTPRequestHandler):
    """Authenticated, bounded read-only scanning API."""

    def log_message(self, format: str, *args: object) -> None:
        # Do not log caller-controlled paths, authorization, image IDs or data.
        return

    def _send(self, status: int, data: dict[str, object]) -> None:
        raw = json.dumps(data, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def _authorized(self) -> bool:
        header = self.headers.get("Authorization", "")
        return hmac.compare_digest(header, "Bearer " + cast(Server, self.server).api_token)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send(200, {"status": "ok"})
            return
        if not self._authorized():
            self._send(401, {"error": "unauthorized"})
            return
        if self.path != "/v1/info":
            self._send(404, {"error": "not found"})
            return
        try:
            self._send(200, database_info())
        except ScanFailure:
            self._send(503, {"error": "scanner database unavailable"})

    def do_POST(self) -> None:
        if not self._authorized():
            self._send(401, {"error": "unauthorized"})
            return
        if self.path != "/v1/scan":
            self._send(404, {"error": "not found"})
            return
        try:
            image_id = _parse_scan_request(self)
        except (TypeError, ValueError):
            self._send(400, {"error": "invalid scan request"})
            return
        if not GUARD.acquire(blocking=False):
            self._send(429, {"error": "scanner busy"})
            return
        try:
            self._send(200, _scan_result(image_id))
        except ScanFailure:
            self._send(503, {"error": "scan unavailable or incomplete"})
        finally:
            GUARD.release()


class Server(ThreadingHTTPServer):
    daemon_threads = True
    api_token: str


def main() -> None:
    server = Server(("0.0.0.0", 8090), Handler)
    server.api_token = token()
    server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
