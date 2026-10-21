#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

# Health snapshot shared by the running bot and the container health probe.
#
# The bot process writes ``<state root>/health.json`` after every health monitor
# cycle. The probe runs in a separate, short-lived process and only reads that file,
# so this module must stay light: standard library, psutil and
# ``pytmbot.utils.state_paths`` only (no telebot, settings or logger imports).

from __future__ import annotations

import json
import math
import os
import tempfile
import time
from collections.abc import Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Final

import psutil

from pytmbot.utils.state_paths import ensure_private_directory, get_state_root_path

SNAPSHOT_FILENAME: Final[str] = "health.json"
SNAPSHOT_SCHEMA_VERSION: Final[int] = 1
SNAPSHOT_FILE_MODE: Final[int] = 0o600
SNAPSHOT_MAX_BYTES: Final[int] = 64 * 1024
# A snapshot stays valid for two monitor intervals plus this grace period.
SNAPSHOT_STALE_GRACE_SECONDS: Final[float] = 60.0
# psutil derives the create time from boot ticks and the boot time in whole seconds.
PROCESS_CREATE_TIME_TOLERANCE_SECONDS: Final[float] = 1.0
# A snapshot written "in the future" means the wall clock moved back.
CLOCK_SKEW_TOLERANCE_SECONDS: Final[float] = 60.0


def get_health_snapshot_path() -> Path:
    """Return where the running bot publishes its health snapshot."""
    return get_state_root_path() / SNAPSHOT_FILENAME


def snapshot_ttl(interval_seconds: float) -> float:
    """Return how long a snapshot written by a monitor with this interval stays fresh."""
    return 2.0 * interval_seconds + SNAPSHOT_STALE_GRACE_SECONDS


def _require_number(payload: Mapping[str, object], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{key!r} must be a number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{key!r} must be finite")
    return number


@dataclass(frozen=True, slots=True)
class HealthSnapshot:
    """Health state of one bot process at one point in time."""

    pid: int
    process_create_time: float
    overall: str
    healthy: bool
    timestamp: float
    stale_after: float
    components: dict[str, str] = field(default_factory=dict)
    schema: int = SNAPSHOT_SCHEMA_VERSION

    def to_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "pid": self.pid,
            "process_create_time": self.process_create_time,
            "overall": self.overall,
            "healthy": self.healthy,
            "timestamp": self.timestamp,
            "stale_after": self.stale_after,
            "components": dict(self.components),
        }

    @classmethod
    def from_payload(cls, payload: object) -> HealthSnapshot:
        """Validate a decoded snapshot document; raise ``ValueError`` when invalid."""
        if not isinstance(payload, dict):
            raise ValueError("snapshot must be a JSON object")

        schema = payload.get("schema")
        if isinstance(schema, bool) or not isinstance(schema, int):
            raise ValueError("'schema' must be an integer")
        if schema != SNAPSHOT_SCHEMA_VERSION:
            raise ValueError(f"unsupported schema version {schema}")

        pid = payload.get("pid")
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            raise ValueError("'pid' must be a positive integer")

        overall = payload.get("overall")
        if not isinstance(overall, str) or not overall:
            raise ValueError("'overall' must be a non-empty string")

        healthy = payload.get("healthy")
        if not isinstance(healthy, bool):
            raise ValueError("'healthy' must be a boolean")

        timestamp = _require_number(payload, "timestamp")
        stale_after = _require_number(payload, "stale_after")
        if stale_after < timestamp:
            raise ValueError("'stale_after' is earlier than 'timestamp'")

        raw_components = payload.get("components", {})
        if not isinstance(raw_components, dict) or not all(
            isinstance(name, str) and isinstance(level, str)
            for name, level in raw_components.items()
        ):
            raise ValueError("'components' must map component names to levels")

        return cls(
            pid=pid,
            process_create_time=_require_number(payload, "process_create_time"),
            overall=overall,
            healthy=healthy,
            timestamp=timestamp,
            stale_after=stale_after,
            components=dict(raw_components),
            schema=schema,
        )


class HealthSnapshotWriter:
    """Atomically publish the health snapshot of the current process."""

    __slots__ = ("_path",)

    def __init__(self, path: Path | None = None) -> None:
        self._path = path if path is not None else get_health_snapshot_path()

    @property
    def path(self) -> Path:
        return self._path

    def write(
        self,
        *,
        overall: str,
        healthy: bool,
        components: Mapping[str, str],
        interval_seconds: float,
    ) -> HealthSnapshot:
        """Write a snapshot that stays fresh for ``snapshot_ttl(interval_seconds)``.

        Raises ``OSError`` when the state directory or file cannot be written.
        """
        now = time.time()
        # Re-read the create time on every write: it includes the boot time, which
        # follows wall-clock steps, so it must match what the probe computes.
        process = psutil.Process()
        snapshot = HealthSnapshot(
            pid=int(process.pid),
            process_create_time=float(process.create_time()),
            overall=overall,
            healthy=healthy,
            timestamp=now,
            stale_after=now + snapshot_ttl(interval_seconds),
            components=dict(components),
        )
        self._write_atomically(snapshot)
        return snapshot

    def remove(self) -> None:
        """Delete the snapshot (best effort), e.g. on clean shutdown."""
        with suppress(OSError):
            self._path.unlink(missing_ok=True)

    def _write_atomically(self, snapshot: HealthSnapshot) -> None:
        directory = ensure_private_directory(self._path.parent)
        file_descriptor, temp_path = tempfile.mkstemp(
            prefix=".health_",
            suffix=".json.tmp",
            dir=str(directory),
            text=True,
        )
        try:
            with os.fdopen(file_descriptor, "w", encoding="utf-8") as temp_file:
                json.dump(
                    snapshot.to_payload(),
                    temp_file,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            os.chmod(temp_path, SNAPSHOT_FILE_MODE)
            os.replace(temp_path, self._path)
        except BaseException:
            with suppress(OSError):
                os.unlink(temp_path)
            raise


class ProbeStatus(IntEnum):
    """Health probe verdicts; the values are the process exit codes."""

    HEALTHY = 0
    UNHEALTHY = 1
    UNKNOWN = 2


@dataclass(frozen=True, slots=True)
class ProbeResult:
    status: ProbeStatus
    reason: str


def read_health_snapshot(path: Path) -> HealthSnapshot:
    """Read and validate a snapshot.

    Raises ``FileNotFoundError`` when it does not exist, ``OSError`` when it cannot
    be read and ``ValueError`` when its content is invalid.
    """
    with path.open("rb") as snapshot_file:
        raw = snapshot_file.read(SNAPSHOT_MAX_BYTES + 1)
    if len(raw) > SNAPSHOT_MAX_BYTES:
        raise ValueError(f"snapshot is larger than {SNAPSHOT_MAX_BYTES} bytes")
    # JSONDecodeError and UnicodeDecodeError are both ValueError subclasses.
    return HealthSnapshot.from_payload(json.loads(raw.decode("utf-8")))


def _writer_process_problem(snapshot: HealthSnapshot) -> str | None:
    """Return why the process that wrote ``snapshot`` is not the live bot, if so."""
    pid = snapshot.pid
    not_running = f"bot process {pid} that wrote the health snapshot is not running"
    try:
        process = psutil.Process(pid)
        create_time = float(process.create_time())
        if process.status() == psutil.STATUS_ZOMBIE:
            return not_running
    except psutil.NoSuchProcess:
        return not_running
    except psutil.Error as error:
        return f"cannot inspect bot process {pid}: {type(error).__name__}"

    if (
        abs(create_time - snapshot.process_create_time)
        > PROCESS_CREATE_TIME_TOLERANCE_SECONDS
    ):
        return (
            f"PID {pid} now belongs to another process; "
            "the bot that wrote the health snapshot has exited"
        )
    return None


def _describe_components(snapshot: HealthSnapshot) -> str:
    problems = [
        f"{name}={level}"
        for name, level in sorted(snapshot.components.items())
        if level != "healthy"
    ]
    return ", ".join(problems) if problems else "no component details"


def evaluate_health_snapshot(
    path: Path | None = None, *, now: float | None = None
) -> ProbeResult:
    """Decide whether the bot is healthy based only on its published snapshot."""
    snapshot_path = path if path is not None else get_health_snapshot_path()
    try:
        snapshot = read_health_snapshot(snapshot_path)
    except FileNotFoundError:
        return ProbeResult(
            ProbeStatus.UNKNOWN,
            f"no health snapshot at {snapshot_path} yet: the bot is still starting, "
            "is not running, or cannot write to its state directory",
        )
    except OSError as error:
        return ProbeResult(
            ProbeStatus.UNHEALTHY,
            f"cannot read health snapshot {snapshot_path}: "
            f"{error.strerror or type(error).__name__}",
        )
    except ValueError as error:
        return ProbeResult(
            ProbeStatus.UNHEALTHY,
            f"invalid health snapshot {snapshot_path}: {error}",
        )

    if (process_problem := _writer_process_problem(snapshot)) is not None:
        return ProbeResult(ProbeStatus.UNHEALTHY, process_problem)

    current_time = time.time() if now is None else now
    age = current_time - snapshot.timestamp
    if age < -CLOCK_SKEW_TOLERANCE_SECONDS:
        return ProbeResult(
            ProbeStatus.UNHEALTHY,
            f"health snapshot is dated {-age:.0f}s in the future (system clock changed?)",
        )
    if current_time > snapshot.stale_after:
        return ProbeResult(
            ProbeStatus.UNHEALTHY,
            f"health snapshot is stale: last update {age:.0f}s ago "
            f"by bot process {snapshot.pid}",
        )
    if not snapshot.healthy:
        return ProbeResult(
            ProbeStatus.UNHEALTHY,
            f"bot reports {snapshot.overall}: {_describe_components(snapshot)}",
        )
    return ProbeResult(
        ProbeStatus.HEALTHY,
        f"bot reports {snapshot.overall}, updated {max(age, 0.0):.0f}s ago",
    )


__all__ = [
    "SNAPSHOT_FILENAME",
    "SNAPSHOT_SCHEMA_VERSION",
    "HealthSnapshot",
    "HealthSnapshotWriter",
    "ProbeResult",
    "ProbeStatus",
    "evaluate_health_snapshot",
    "get_health_snapshot_path",
    "read_health_snapshot",
    "snapshot_ttl",
]
