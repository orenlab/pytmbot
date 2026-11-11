"""Read-only, bounded local Docker image scans using externally provisioned Trivy."""

from __future__ import annotations

import json
import os
import re
import resource
import subprocess
import tempfile
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
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
    counts: dict[str, int]
    fixable: int
    findings: tuple[tuple[str, str, str], ...]
    trivy_schema: int | None


def parse_report(raw: bytes, *, image_id: str) -> ScanSummary:
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
    counts: Counter[str] = Counter()
    fixable = 0
    selected: list[tuple[str, str, str]] = []
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
            severity = vulnerability.get("Severity")
            if not isinstance(severity, str) or severity not in _SEVERITIES:
                severity = "UNKNOWN"
            counts[severity] += 1
            fixed = vulnerability.get("FixedVersion")
            if isinstance(fixed, str) and fixed.strip():
                fixable += 1
            if len(selected) < 8 and severity in ("CRITICAL", "HIGH"):
                vuln_id = vulnerability.get("VulnerabilityID")
                package = vulnerability.get("PkgName")
                if isinstance(vuln_id, str) and isinstance(package, str):
                    selected.append((severity, vuln_id[:48], package[:64]))
    version = obj.get("SchemaVersion")
    return ScanSummary(
        image_id=image_id,
        scanned_at=datetime.now(UTC).isoformat(timespec="seconds"),
        counts={severity: counts[severity] for severity in _SEVERITIES},
        fixable=fixable,
        findings=tuple(selected),
        trivy_schema=version if type(version) is int else None,
    )


def _constrain_output(max_bytes: int) -> None:
    """POSIX/Linux child limit; Trivy cannot write an unbounded report."""
    resource.setrlimit(resource.RLIMIT_FSIZE, (max_bytes, max_bytes))


def scan_local_image(image_id: str, config: TrivyConfig) -> ScanSummary:
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
    argv = [
        str(binary), "image", "--image-src", "docker",
        "--docker-host", config.docker_host, "--scanners", "vuln",
        "--format", "json", "--quiet", "--skip-db-update",
        "--skip-java-db-update", "--skip-check-update",
        "--skip-version-check", "--disable-telemetry",
        "--list-all-pkgs=false", "--cache-dir", str(cache),
        "--timeout", f"{config.timeout_seconds}s",
        f"sha256:{image_id}",
    ]
    # File-size limit enforced in the child and in the parent after exit.
    # Omit HOME, proxy, registry and cloud authentication variables.
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(cache),
        "TMPDIR": str(cache),
        "LANG": "C",
        "DOCKER_CONFIG": str(cache / "no-docker-credentials"),
        "TRIVY_DISABLE_TELEMETRY": "true",
    }
    try:
        with tempfile.TemporaryFile(mode="w+b") as output:
            completed = subprocess.run(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=output,
                stderr=subprocess.DEVNULL,
                env=env,
                timeout=config.timeout_seconds + 10,
                check=False,
                preexec_fn=lambda: _constrain_output(config.max_report_bytes),
            )
            if completed.returncode:
                raise ScanError("Trivy failed. Check runner configuration and offline DB.")
            if output.tell() > config.max_report_bytes:
                raise ScanError("Trivy report exceeds the configured size limit.")
            output.seek(0)
            raw = output.read(config.max_report_bytes + 1)
            if len(raw) > config.max_report_bytes:
                raise ScanError("Trivy report exceeds the configured size limit.")
    except subprocess.TimeoutExpired as error:
        raise ScanError("Trivy scan timed out.") from error
    except OSError as error:
        raise ScanError("Trivy could not run in the configured environment.") from error
    return parse_report(raw, image_id=image_id)


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
                        summary = scan_local_image(image_id, self.config)
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
