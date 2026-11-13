"""Bounded, private SQLite history for completed Trivy vulnerability scans."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from pytmbot.plugins.trivy.runner import ScanSummary


class HistoryError(Exception):
    """Scan history could not be safely recorded or retrieved."""


@dataclass(frozen=True, slots=True)
class HistoryDelta:
    previous: bool
    new_ids: tuple[str, ...]


def _prepare_storage(path: Path) -> None:
    if not path.parent.is_dir():
        raise HistoryError("Trivy history directory does not exist.")
    directory_mode = path.parent.stat().st_mode
    if directory_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise HistoryError("Trivy history directory must be private.")
    if path.is_symlink():
        raise HistoryError("Trivy history must not be a symlink.")
    if path.exists():
        _check_existing_file(path)
        return
    fd = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    os.close(fd)


def _check_existing_file(path: Path) -> None:
    mode = path.stat().st_mode
    if not stat.S_ISREG(mode) or mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise HistoryError("Trivy history must be a private regular file.")


def _decode_snapshot(raw: str) -> ScanSummary:
    decoded = json.loads(raw)
    if not isinstance(decoded, dict):
        raise ValueError("Invalid Trivy history payload.")
    obj: dict[str, Any] = decoded
    return ScanSummary(
        **{
            **obj,
            "findings": tuple(tuple(x) for x in obj["findings"]),
            "vulnerability_ids": tuple(obj["vulnerability_ids"]),
        }
    )


class ScanHistory:
    """Persist only bounded, sanitized summaries; never store raw scanner JSON."""

    def __init__(self, filename: str, *, max_records: int = 128) -> None:
        self.path = Path(filename)
        self.max_records = max_records
        try:
            _prepare_storage(self.path)
            with self._connect() as db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS scans ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "image_id TEXT NOT NULL, scanned_at TEXT NOT NULL, "
                    "payload TEXT NOT NULL)"
                )
                db.execute(
                    "CREATE INDEX IF NOT EXISTS scans_image ON scans(image_id, id)"
                )
        except (OSError, sqlite3.Error) as error:
            raise HistoryError("Trivy scan history storage is unavailable.") from error

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(str(self.path), timeout=2)
        try:
            db.execute("PRAGMA busy_timeout=2000")
            db.execute("PRAGMA synchronous=FULL")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _new_ids(
        previous: tuple[str, ...] | None, summary: ScanSummary
    ) -> tuple[str, ...]:
        if previous is None:
            return ()
        old = _decode_snapshot(previous[0])
        return tuple(
            sorted(set(summary.vulnerability_ids) - set(old.vulnerability_ids))
        )

    def append(self, summary: ScanSummary) -> HistoryDelta:
        """Compare with the last completed snapshot and store the new result."""
        payload = json.dumps(asdict(summary), separators=(",", ":"), ensure_ascii=True)
        if len(payload) > 65536:
            raise HistoryError("Scan audit entry exceeds the storage limit.")
        try:
            with self._connect() as db:
                previous = db.execute(
                    "SELECT payload FROM scans WHERE image_id = ? ORDER BY id DESC LIMIT 1",
                    (summary.image_id,),
                ).fetchone()
                delta = self._new_ids(previous, summary)
                db.execute(
                    "INSERT INTO scans(image_id, scanned_at, payload) VALUES (?, ?, ?)",
                    (summary.image_id, summary.scanned_at, payload),
                )
                db.execute(
                    "DELETE FROM scans WHERE id NOT IN "
                    "(SELECT id FROM scans ORDER BY id DESC LIMIT ?)",
                    (self.max_records,),
                )
            return HistoryDelta(previous=previous is not None, new_ids=delta)
        except (OSError, sqlite3.Error, ValueError, TypeError, KeyError) as error:
            raise HistoryError(
                "Unable to store verified Trivy scan history."
            ) from error

    def recent(self, *, limit: int = 8) -> list[ScanSummary]:
        try:
            with self._connect() as db:
                rows = db.execute(
                    "SELECT payload FROM scans ORDER BY id DESC LIMIT ?",
                    (max(1, min(limit, 16)),),
                ).fetchall()
            return [_decode_snapshot(row[0]) for row in rows]
        except (OSError, sqlite3.Error, ValueError, TypeError, KeyError) as error:
            raise HistoryError("Unable to load Trivy scan history.") from error
