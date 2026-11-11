"""Read-only, bounded local Docker image scans using externally provisioned Trivy."""

from __future__ import annotations

import hashlib
import json
import os
import re
import select
import signal
import subprocess
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Thread
from typing import Final

from pytmbot.adapters.docker.client import docker_client_context
from pytmbot.adapters.docker.images_info import list_images_tolerant
from pytmbot.models.settings_model import TrivyConfig

_ID_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9a-f]{64}\Z")
_SEVERITIES: Final[tuple[str, ...]] = (
    "CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"
)


class ScanError(Exception):
    """A scan failed; do not treat it as zero vulnerabilities."""


def local_image_ids(*, limit: int) -> list[str]:
    """Return unique immutable Docker image IDs without pulling remote images."""
    with docker_client_context() as client:
        images = list_images_tolerant(client, include_intermediate=False)
        identifiers = sorted({
            image_id
            for image in images
            if (image_id := getattr(image, "id", "").removeprefix("sha256:"))
            and _ID_PATTERN.fullmatch(image_id)
        })
    if len(identifiers) > limit:
        raise ScanError(f"Image count exceeds configured limit ({limit}).")
    return identifiers


def resolve_local_id(prefix: str, *, limit: int) -> str:
    """Resolve a displayed short ID to exactly one currently installed image."""
    if not re.fullmatch(r"[0-9a-f]{12}", prefix):
        raise ScanError("Invalid local image selection.")
    matches = [item for item in local_image_ids(limit=limit) if item.startswith(prefix)]
    if len(matches) != 1:
        raise ScanError("Image was removed or its selection is ambiguous. Refresh.")
    return matches[0]


@dataclass(frozen=True, slots=True)
class ScanSummary:
    image_id: str
    scanned_at: str
    scanner_sha256: str
    db_schema: int
    db_updated_at: str
    counts: dict[str, int]
    fixable: int
    findings: tuple[tuple[str, str, str], ...]
    trivy_schema: int | None
    vulnerability_ids: tuple[str, ...] = ()


def _vulnerability_rows(results: list[object]) -> list[dict[str, object]]:
    """Require a complete, structured report before counting any findings."""
    rows: list[dict[str, object]] = []
    for result in results:
        if not isinstance(result, dict):
            raise ScanError("Scanner returned invalid result entries.")
        vulnerabilities = result.get("Vulnerabilities", [])
        if vulnerabilities is None:
            vulnerabilities = []
        if not isinstance(vulnerabilities, list):
            raise ScanError("Scanner returned invalid vulnerability entries.")
        for vulnerability in vulnerabilities:
            if not isinstance(vulnerability, dict):
                raise ScanError("Scanner returned invalid vulnerability entries.")
            rows.append(vulnerability)
    return rows


def _severity(raw: object) -> str:
    return raw if isinstance(raw, str) and raw in _SEVERITIES else "UNKNOWN"


def _selected_finding(vulnerability: dict[str, object], severity: str) -> tuple[str, str, str] | None:
    if severity not in ("CRITICAL", "HIGH"):
        return None
    identifier = vulnerability.get("VulnerabilityID")
    package = vulnerability.get("PkgName")
    if not isinstance(identifier, str) or not isinstance(package, str):
        return None
    return severity, identifier[:48], package[:64]


def _aggregate_vulnerabilities(
    rows: list[dict[str, object]],
) -> tuple[dict[str, int], int, tuple[tuple[str, str, str], ...], tuple[str, ...]]:
    counts: Counter[str] = Counter()
    fixable = 0
    selected: list[tuple[str, str, str]] = []
    vulnerability_ids: set[str] = set()
    for item in rows:
        severity = _severity(item.get("Severity"))
        counts[severity] += 1
        identifier = item.get("VulnerabilityID")
        if isinstance(identifier, str) and 0 < len(identifier) <= 120:
            vulnerability_ids.add(identifier)
            if len(vulnerability_ids) > 1000:
                raise ScanError("Too many unique vulnerabilities for audited scan.")
        fixed = item.get("FixedVersion")
        if isinstance(fixed, str) and fixed.strip():
            fixable += 1
        if len(selected) < 8:
            finding = _selected_finding(item, severity)
            if finding is not None:
                selected.append(finding)
    return (
        {severity: counts[severity] for severity in _SEVERITIES},
        fixable,
        tuple(selected),
        tuple(sorted(vulnerability_ids)),
    )


def parse_report(
    raw: bytes, *, image_id: str,
    scanner_sha256: str = "", db_schema: int = 0, db_updated_at: str = "",
) -> ScanSummary:
    """Validate a bounded Trivy JSON report; never render arbitrary fields."""
    try:
        obj = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as error:
        raise ScanError("Scanner returned invalid JSON.") from error
    if not isinstance(obj, dict) or not isinstance(obj.get("Results"), list):
        raise ScanError("Scanner returned an incomplete report.")
    results = obj["Results"]
    if not results:
        raise ScanError("Scanner returned no scan targets; result is inconclusive.")
    counts, fixable, selected, identifiers = _aggregate_vulnerabilities(
        _vulnerability_rows(results)
    )
    version = obj.get("SchemaVersion")
    return ScanSummary(
        image_id=image_id,
        scanned_at=datetime.now(UTC).isoformat(timespec="seconds"),
        scanner_sha256=scanner_sha256,
        db_schema=db_schema,
        db_updated_at=db_updated_at,
        counts=counts,
        fixable=fixable,
        findings=selected,
        trivy_schema=version if type(version) is int else None,
        vulnerability_ids=identifiers,
    )


@dataclass(frozen=True, slots=True)
class DatabaseInfo:
    schema: int
    updated_at: str


def verify_scanner_binary(path: Path, expected_sha256: str) -> None:
    """Fail closed if the executable differs from the operator-pinned hash."""
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise ScanError("Configured Trivy executable cannot be verified.") from error
    if digest.hexdigest() != expected_sha256:
        raise ScanError("Configured Trivy binary SHA-256 mismatch.")


def read_database_metadata(cache: Path, *, max_age_hours: int) -> DatabaseInfo:
    """Fail closed when the offline vulnerability DB is unavailable or stale."""
    metadata = cache / "db" / "metadata.json"
    database = cache / "db" / "trivy.db"
    try:
        if not database.is_file() or metadata.stat().st_size > 8192:
            raise ScanError("Trivy vulnerability database metadata is unavailable.")
        record = json.loads(metadata.read_bytes())
        if not isinstance(record, dict):
            raise ValueError("Expected object")
        schema = record["Version"]
        value = record["UpdatedAt"]
        if type(schema) is not int or schema <= 0 or not isinstance(value, str):
            raise ValueError("Invalid metadata fields")
        updated = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if updated.tzinfo is None:
            raise ValueError("Timestamp missing timezone")
        age = datetime.now(UTC) - updated.astimezone(UTC)
        if age < -timedelta(minutes=5) or age > timedelta(hours=max_age_hours):
            raise ScanError("Trivy vulnerability database is stale or future-dated.")
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ScanError("Trivy vulnerability database metadata is invalid.") from error
    return DatabaseInfo(schema=schema, updated_at=updated.astimezone(UTC).isoformat())


def _bounded_stdout(
    argv: list[str], *,
    env: dict[str, str], cwd: str,
    timeout_seconds: int, max_bytes: int, cancel: Event | None = None,
) -> bytes:
    """Read at most max_bytes from a subprocess; terminate on size or time.

    Do not use preexec_fn: pyTMBot has other threads, and preexec_fn can
    deadlock before exec. The OS/container must separately enforce CPU/RAM.
    """
    try:
        proc = subprocess.Popen(
            argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, env=env, cwd=cwd,
            start_new_session=True,
        )
    except OSError as error:
        raise ScanError("Trivy executable could not start.") from error
    chunks: list[bytes] = []
    total = 0
    deadline = time.monotonic() + timeout_seconds + 10
    try:
        stdout = proc.stdout
        if stdout is None:
            raise ScanError("Trivy stdout pipe is unavailable.")
        fd = stdout.fileno()
        while True:
            if cancel is not None and cancel.is_set():
                raise ScanError("Trivy scan was cancelled.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ScanError("Trivy scan timed out.")
            readable, _, _ = select.select([fd], [], [], min(1.0, remaining))
            if not readable:
                continue
            chunk = os.read(fd, min(65536, max_bytes - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise ScanError("Trivy report exceeds the configured size limit.")
            chunks.append(chunk)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ScanError("Trivy scan timed out.")
        try:
            rc = proc.wait(timeout=remaining)
        except subprocess.TimeoutExpired as error:
            raise ScanError("Trivy scan timed out.") from error
        if rc != 0:
            raise ScanError("Trivy failed. Check runner configuration and offline DB.")
        return b"".join(chunks)
    finally:
        if proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait(timeout=5)
        if proc.stdout is not None:
            proc.stdout.close()


def scan_local_image(
    image_id: str, config: TrivyConfig, *, cancel: Event | None = None,
) -> ScanSummary:
    """Scan a verified local immutable image, without shell or remote fallback.

    The scanner binary, socket and cache are operator-managed. No credentials
    or host environment are forwarded to the child process.
    """
    if not _ID_PATTERN.fullmatch(image_id):
        raise ScanError("Invalid image ID.")
    if image_id not in local_image_ids(limit=config.max_images):
        raise ScanError("Image is no longer installed.")
    binary = Path(config.executable)
    cache = Path(config.cache_dir)
    socket = Path(config.docker_host.removeprefix("unix://"))
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise ScanError("Configured Trivy executable is unavailable.")
    if not socket.is_socket():
        raise ScanError("Configured local Docker socket is unavailable.")
    if not cache.is_dir():
        raise ScanError("Configured Trivy cache does not exist.")
    verify_scanner_binary(binary, config.scanner_sha256)
    database_info = read_database_metadata(cache, max_age_hours=config.max_db_age_hours)
    argv = [
        str(binary), "image", "--config", "/dev/null",
        "--ignorefile", "/dev/null", "--exit-code", "0",
        "--image-src", "docker",
        "--docker-host", config.docker_host, "--scanners", "vuln",
        "--format", "json", "--quiet", "--skip-db-update",
        "--skip-java-db-update", "--skip-check-update",
        "--skip-version-check", "--disable-telemetry",
        "--list-all-pkgs=false", "--offline-scan",
        "--parallel", "1",
        "--max-image-size", f"{config.max_image_size_mb}MB",
        "--cache-dir", str(cache),
        "--timeout", f"{config.timeout_seconds}s",
        f"sha256:{image_id}",
    ]
    # Prevent implicit trivy.yaml/.trivyignore from influencing scan results.
    # No inherited proxy, registry, or cloud authentication environment.
    # Child output is bounded in _bounded_stdout; external OS isolation is required.
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(cache),
        "TMPDIR": str(cache),
        "LANG": "C",
        "DOCKER_CONFIG": str(cache / "no-docker-credentials"),
        "TRIVY_DISABLE_TELEMETRY": "true",
    }
    raw = _bounded_stdout(
        argv, env=env, cwd="/",
        timeout_seconds=config.timeout_seconds,
        max_bytes=config.max_report_bytes, cancel=cancel,
    )
    return parse_report(
        raw, image_id=image_id, scanner_sha256=config.scanner_sha256,
        db_schema=database_info.schema, db_updated_at=database_info.updated_at,
    )


@dataclass(frozen=True, slots=True)
class ScanJob:
    chat_id: int
    user_id: int
    image_ids: tuple[str, ...]


class ScanQueue:
    """One worker; bounded queue; no inline scanning in Telegram handlers."""

    def __init__(
        self,
        config: TrivyConfig,
        publish: Callable[[ScanJob, str, ScanSummary | None], None],
    ) -> None:
        self.config = config
        self.publish = publish
        self._jobs: Queue[ScanJob] = Queue(maxsize=config.max_queued_jobs)
        self._stop = Event()
        self._worker = Thread(target=self._run, name="trivy-scan", daemon=True)
        self._worker.start()

    def submit(self, job: ScanJob) -> bool:
        if self._stop.is_set():
            return False
        try:
            self._jobs.put_nowait(job)
        except Full:
            return False
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._jobs.get(timeout=0.25)
            except Empty:
                continue
            try:
                for image_id in job.image_ids:
                    if self._stop.is_set():
                        break
                    try:
                        summary = scan_local_image(
                            image_id, self.config, cancel=self._stop,
                        )
                    except Exception:
                        # Docker transport, Trivy and parsing failures are not zero CVEs.
                        summary = None
                    try:
                        self.publish(
                            job,
                            "complete" if summary is not None else "failed",
                            summary,
                        )
                    except Exception:
                        # Telegram delivery failures must not kill the scan worker.
                        pass
            finally:
                self._jobs.task_done()

    def cleanup(self) -> None:
        self._stop.set()
        self._worker.join(timeout=2)
