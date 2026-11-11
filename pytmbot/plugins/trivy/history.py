"""Bounded, private, persistent audit history for completed Trivy scans."""

from __future__ import annotations

import json
import os
import sqlite3
import stat
from dataclasses import asdict, dataclass
from pathlib import Path

from pytmbot.plugins.trivy.runner import ScanSummary


class HistoryError(Exception):
    """History cannot be trusted or persisted."""


@dataclass(frozen=True, slots=True)
class HistoryDelta:
    previous: bool
    new_ids: tuple[str, ...]


class ScanHistory:
    """SQLite snapshots; no credentials, raw scan JSON, or container environment."""

    def __init__(self, filename: str, *, max_records: int = 128) -> None:
        self.path = Path(filename)
        parent = self.path.parent
        try:
            parent_mode = parent.stat().st_mode
            if not parent.is_dir() or parent_mode & (stat.S_IWGRP | stat.S_IWOTH):
                raise HistoryError("Trivy history directory must be private.")
            if self.path.is_symlink():
                raise HistoryError("Trivy history may not be a symlink.")
            if self.path.exists():
                mode = self.path.stat().st_mode
                if not stat.S_ISREG(mode) or mode & (stat.S_IRWXG | stat.S_IRWXO):
                    raise HistoryError("Trivy history must be a private regular file.")
            else:
                fd = os.open(
                    self.path,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
                    0o600,
                )
                os.close(fd)
            self.max_records = max_records
            with self._connect() as db:
                db.execute(
                    "CREATE TABLE IF NOT EXISTS scans ("
                    "id INTEGER PRIMARY KEY AUTOINCREMENT, "
                    "image_id TEXT NOT NULL, scanned_at TEXT NOT NULL, "
                    "payload TEXT NOT NULL)"
                )
                db.execute("CREATE INDEX IF NOT EXISTS scans_image ON scans(image_id, id)")
        except (OSError, sqlite3.Error) as error:
            raise HistoryError("Trivy scan history storage is unavailable.") from error

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(str(self.path), timeout=2)
        db.execute("PRAGMA busy_timeout=2000")
        db.execute("PRAGMA synchronous=FULL")
        return db

    def append(self, summary: ScanSummary) -> HistoryDelta:
        """Atomically compare with the previous completed scan and persist."""
        payload = json.dumps(asdict(summary), separators=(",", ":"), ensure_ascii=True)
        if len(payload) > 65536:
            raise HistoryError("Scan audit entry exceeds the storage limit.")
        try:
            with self._connect() as db:
                previous = db.execute(
                    "SELECT payload FROM scans WHERE image_id = ? ORDER BY id DESC LIMIT 1",
                    (summary.image_id,),
                ).fetchone()
                new_ids: tuple[str, ...] = ()
                if previous is not None:
                    old = json.loads(previous[0])
                    prior = set(old.get("vulnerability_ids", []))
                    new_ids = tuple(sorted(set(summary.vulnerability_ids) - prior))
                db.execute(
                    "INSERT INTO scans(image_id, scanned_at, payload) VALUES (?, ?, ?)",
                    (summary.image_id, summary.scanned_at, payload),
                )
                db.execute(
                    "DELETE FROM scans WHERE id NOT IN "
                    "(SELECT id FROM scans ORDER BY id DESC LIMIT ?)",
                    (self.max_records,),
                )
            return HistoryDelta(previous=previous is not None, new_ids=new_ids)
        except (sqlite3.Error, ValueError, TypeError) as error:
            raise HistoryError("Unable to store verified Trivy scan history.") from error

    def recent(self, *, limit: int = 8) -> list[ScanSummary]:
        try:
            with self._connect() as db:
                rows = db.execute(
                    "SELECT payload FROM scans ORDER BY id DESC LIMIT ?",
                    (max(1, min(limit, 16)),),
                ).fetchall()
            return [
                ScanSummary(**{
                    **(obj := json.loads(row[0])),
                    "findings": tuple(tuple(x) for x in obj["findings"]),
                    "vulnerability_ids": tuple(obj["vulnerability_ids"]),
                })
                for row in rows
            ]
        except (sqlite3.Error, ValueError, TypeError, KeyError) as error:
            raise HistoryError("Unable to load Trivy scan history.") from error
