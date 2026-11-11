"""Bounded HTTP client for an isolated local Trivy scanner service."""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Event, Thread
from typing import Final
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from pytmbot.adapters.docker.client import docker_client_context
from pytmbot.adapters.docker.images_info import list_images_tolerant
from pytmbot.models.settings_model import TrivyConfig

_HTTP = build_opener(ProxyHandler({}))

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




def _private_token(path: str) -> str:
    """Read a Docker secret, never from a public config or inherited env."""
    try:
        value = Path(path).read_text(encoding="utf-8").strip()
    except OSError as error:
        raise ScanError("Trivy worker authentication secret is unavailable.") from error
    if len(value) < 32 or len(value) > 256:
        raise ScanError("Trivy worker authentication secret is invalid.")
    return value


def scan_local_image(
    image_id: str, config: TrivyConfig, *, cancel: Event | None = None,
) -> ScanSummary:
    """Send only a verified local image ID to the private authenticated worker."""
    if not _ID_PATTERN.fullmatch(image_id):
        raise ScanError("Invalid image ID.")
    if cancel is not None and cancel.is_set():
        raise ScanError("Trivy scan cancelled.")
    if image_id not in local_image_ids(limit=config.max_images):
        raise ScanError("Image is no longer installed.")
    request = Request(
        config.endpoint.rstrip("/") + "/v1/scan",
        data=json.dumps({"image_id": f"sha256:{image_id}"}).encode("ascii"),
        headers={
            "Authorization": "Bearer " + _private_token(config.token_file),
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with _HTTP.open(request, timeout=config.timeout_seconds + 20) as response:
            if response.status != 200:
                raise ScanError("Trivy worker returned a failure.")
            raw = response.read(config.max_report_bytes + 2049)
    except (HTTPError, URLError, OSError, TimeoutError) as error:
        raise ScanError("Trivy worker is unavailable or scan failed.") from error
    if len(raw) > config.max_report_bytes + 2048:
        raise ScanError("Trivy worker report exceeds configured size limit.")
    try:
        document = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as error:
        raise ScanError("Trivy worker returned invalid JSON.") from error
    if not isinstance(document, dict) or document.get("image_id") != "sha256:" + image_id:
        raise ScanError("Trivy worker result does not match the requested image.")
    report = document.get("report")
    if not isinstance(report, dict):
        raise ScanError("Trivy worker result is incomplete.")
    metadata = document.get("db_updated_at")
    schema = document.get("db_schema")
    version = document.get("scanner_version")
    if not isinstance(metadata, str) or type(schema) is not int or not isinstance(version, str):
        raise ScanError("Trivy worker returned invalid provenance.")
    try:
        db_timestamp = datetime.fromisoformat(metadata.replace("Z", "+00:00"))
        if db_timestamp.tzinfo is None:
            raise ValueError("Missing timezone")
        if (datetime.now(UTC) - db_timestamp.astimezone(UTC)).total_seconds() > config.max_db_age_hours * 3600:
            raise ScanError("Trivy vulnerability database is stale.")
    except ValueError as error:
        raise ScanError("Trivy worker returned invalid DB timestamp.") from error
    if cancel is not None and cancel.is_set():
        raise ScanError("Trivy scan cancelled.")
    return parse_report(
        json.dumps(report).encode("utf-8"), image_id=image_id,
        scanner_sha256=version[:48], db_schema=schema, db_updated_at=metadata,
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
