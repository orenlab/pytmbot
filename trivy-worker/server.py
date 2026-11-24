"""Private HTTP adapter for the official Trivy client/server containers.

The API accepts only immutable local image IDs. It does not accept arbitrary
Trivy commands, image names, paths, registry URLs, flags, or Docker operations.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import re
import select
import signal
import subprocess  # nosec B404 - isolated worker invokes a fixed Trivy CLI
import time
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import BoundedSemaphore
from typing import Any, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import ProxyHandler, Request, build_opener

TRIVY_SERVER = "http://trivy-db:4954"
DOCKER_API = "http://trivy-docker-proxy:2375"
DOCKER_HOST = "tcp://trivy-docker-proxy:2375"
IMAGE_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
HTTP = build_opener(ProxyHandler({}))
GUARD = BoundedSemaphore(value=1)
# Hard limits shared with pytmbot.plugins.trivy.runner / TrivyConfig.
MAX_REPORT_BYTES = 2_097_152
MAX_IMAGE_MB = 1024
TIMEOUT = 180
MAX_DB_AGE_HOURS = 48
_LOGGER = logging.getLogger("pytmbot.trivy.worker")


class ScanFailure(Exception):
    """A scan failed and cannot be represented as a clean vulnerability result."""


class _JsonFormatter(logging.Formatter):
    """One JSON object per line, matching pyTMBot's structured log fields."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "module": record.module,
            "msg": record.getMessage(),
        }
        context = getattr(record, "context", None)
        if isinstance(context, dict):
            payload.update(context)
        return json.dumps(
            payload, ensure_ascii=False, default=str, separators=(",", ":")
        )


def _log_level(name: str) -> int:
    level = getattr(logging, name.upper(), logging.INFO)
    return level if isinstance(level, int) else logging.INFO


def configure_logging() -> None:
    """Route worker logs to stderr as JSON lines, controlled by LOG_LEVEL."""
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(_log_level(os.environ.get("LOG_LEVEL", "INFO")))


def secret_file(path: str) -> str:
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise ValueError("Trivy worker secret is unavailable") from exc
    if len(value) < 32 or len(value) > 256:
        raise ValueError("Trivy worker token must contain 32-256 characters")
    return value


def token() -> str:
    return secret_file(
        os.environ.get("TRIVY_WORKER_TOKEN_FILE", "/run/secrets/trivy_worker_token")
    )


def _get_json(url: str, *, limit: int = 8192) -> dict[str, Any]:
    try:
        with HTTP.open(
            Request(
                url,
                method="GET",
                headers={
                    "Trivy-Token": secret_file(
                        os.environ.get(
                            "TRIVY_SERVER_TOKEN_FILE", "/run/secrets/trivy_server_token"
                        )
                    )
                }
                if url.startswith(TRIVY_SERVER + "/")
                else {},
            ),
            timeout=5,
        ) as response:
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


def verified_image(image_id: str) -> str:
    """Return the Docker-canonical ID after verifying it is locally installed."""
    if not IMAGE_RE.fullmatch(image_id):
        raise ScanFailure("Invalid immutable local image ID")
    path = quote(image_id, safe=":")
    obj = _get_json(f"{DOCKER_API}/images/{path}/json", limit=262144)
    canonical = obj.get("Id")
    if canonical != image_id or not isinstance(canonical, str):
        raise ScanFailure("Image no longer matches requested local ID")
    if not IMAGE_RE.fullmatch(canonical):
        raise ScanFailure("Docker returned an invalid image ID")
    return canonical


def database_info(*, max_age_hours: int = MAX_DB_AGE_HOURS) -> dict[str, str | int]:
    info = _get_json(f"{TRIVY_SERVER}/version")
    db = info.get("VulnerabilityDB")
    if not isinstance(db, dict):
        raise ScanFailure("Trivy vulnerability database is unavailable")
    version = db.get("Version")
    updated = db.get("UpdatedAt")
    if (
        not isinstance(version, int)
        or isinstance(version, bool)
        or not isinstance(updated, str)
    ):
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
        "trivy",
        "image",
        "--server",
        TRIVY_SERVER,
        "--image-src",
        "docker",
        "--docker-host",
        DOCKER_HOST,
        "--format",
        "json",
        "--scanners",
        "vuln",
        "--quiet",
        "--no-progress",
        "--offline-scan",
        "--config",
        "/dev/null",
        "--ignorefile",
        "/dev/null",
        "--exit-code",
        "0",
        "--parallel",
        "1",
        "--max-image-size",
        f"{MAX_IMAGE_MB}MB",
        "--skip-check-update",
        "--disable-telemetry",
        "--timeout",
        f"{TIMEOUT}s",
        image_id,
    ]


def _scanner_env() -> dict[str, str]:
    return {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        # Container-private tmpfs; never the host /tmp.
        "HOME": "/tmp",  # nosec B108
        "TMPDIR": "/tmp",  # nosec B108
        "LANG": "C",
        "DOCKER_CONFIG": "/tmp/no-docker-credentials",  # nosec B108
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
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            # Keep the original scan failure; the process is already signalled.
            _LOGGER.warning("bot.plugins.trivy.worker.scan.stop.timeout")
    if proc.stdout is not None:
        proc.stdout.close()


def bounded_scan(image_id: str) -> dict[str, Any]:
    """Run a single Docker-only image scan with bounded time and output."""
    try:
        env = _scanner_env()
    except (OSError, ValueError) as exc:
        raise ScanFailure("Trivy scanner credentials are unavailable") from exc
    try:
        # image_id is the Docker-canonical value returned by verified_image()
        # and always matches IMAGE_RE, so it cannot add command-line options.
        # codeql[py/command-line-injection]
        proc = subprocess.Popen(  # nosec B603 - fixed argv, validated local ID
            _scanner_args(image_id),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
            cwd="/",
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
    started = time.monotonic()
    canonical_id = verified_image(image_id)
    context: dict[str, object] = {"image": canonical_id.removeprefix("sha256:")[:12]}
    _LOGGER.info("bot.plugins.trivy.worker.scan.start", extra={"context": context})
    try:
        info = database_info()
        report = bounded_scan(canonical_id)
        verified_image(canonical_id)
    except ScanFailure as exc:
        _LOGGER.warning(
            "bot.plugins.trivy.worker.scan.fail",
            extra={
                "context": {
                    **context,
                    "error": str(exc),
                    "duration_ms": round((time.monotonic() - started) * 1000),
                }
            },
        )
        raise
    _LOGGER.info(
        "bot.plugins.trivy.worker.scan.complete",
        extra={
            "context": {
                **context,
                "duration_ms": round((time.monotonic() - started) * 1000),
            }
        },
    )
    return {"image_id": canonical_id, **info, "report": report}


class Handler(BaseHTTPRequestHandler):
    """Authenticated, bounded read-only scanning API."""

    # Bound idle request reads so a stalled client cannot hold a thread forever.
    timeout = 30

    # Dispatched by BaseHTTPRequestHandler for request logging.
    # codeclone: ignore[dead-code]
    def log_message(  # pylint: disable=arguments-differ
        self, format_: str, *args: object
    ) -> None:
        # Do not log caller-controlled paths, authorization, image IDs or data.
        return

    def _send(self, status: int, data: Mapping[str, object]) -> None:
        raw = json.dumps(data, separators=(",", ":")).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        try:
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            # The caller went away; do not emit a traceback from the server thread.
            return

    def _authorized(self) -> bool:
        header = self.headers.get("Authorization", "")
        # Headers are decoded as Latin-1, so compare bytes: compare_digest()
        # rejects non-ASCII str input with TypeError.
        allowed = hmac.compare_digest(
            header.encode("utf-8", "replace"),
            ("Bearer " + cast(Server, self.server).api_token).encode(),
        )
        if not allowed:
            _LOGGER.warning("bot.plugins.trivy.worker.auth.reject")
        return allowed

    # Dispatched dynamically by BaseHTTPRequestHandler.
    # codeclone: ignore[dead-code]
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
        except ScanFailure as exc:
            _LOGGER.warning(
                "bot.plugins.trivy.worker.info.fail",
                extra={"context": {"error": str(exc)}},
            )
            self._send(503, {"error": "scanner database unavailable"})

    # Dispatched dynamically by BaseHTTPRequestHandler.
    # codeclone: ignore[dead-code]
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
    configure_logging()
    server = Server(("0.0.0.0", 8090), Handler)  # nosec B104 - private network only
    server.api_token = token()
    _LOGGER.info(
        "bot.plugins.trivy.worker.start",
        extra={"context": {"port": 8090, "pid": os.getpid()}},
    )
    server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
    main()
