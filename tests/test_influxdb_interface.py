from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

import pytest

import pytmbot.db.influxdb_interface as influx_module
from pytmbot.db.influxdb_interface import InfluxDBConfig, InfluxDBInterface
from pytmbot.exceptions import InfluxDBQueryError, InfluxDBWriteError


@dataclass
class _QueryAPIStub:
    calls: list[tuple[str, str]]

    def query(self, query: str, org: str) -> list[Any]:
        self.calls.append((query, org))
        return []


@dataclass
class _WriteAPIStub:
    failures_before_success: int
    calls: int = 0

    def write(self, bucket: str, record: object) -> None:
        del bucket, record
        self.calls += 1
        if self.calls <= self.failures_before_success:
            raise RuntimeError("temporary write failure")


def _build_interface(
    bucket: str = "metrics",
) -> tuple[InfluxDBInterface, _QueryAPIStub]:
    interface = InfluxDBInterface(
        InfluxDBConfig(
            url="http://localhost:8086",
            token="token",
            org="org",
            bucket=bucket,
            debug_mode=False,
        )
    )
    query_api = _QueryAPIStub(calls=[])
    interface._query_api = cast(Any, query_api)
    return interface, query_api


def test_query_data_builds_sanitized_flux_query() -> None:
    interface, query_api = _build_interface()

    result = interface.query_data(
        measurement="system_metrics",
        start="-1h",
        stop="now()",
        field="cpu_usage",
    )

    assert result == []
    assert query_api.calls
    query, org = query_api.calls[0]
    assert org == "org"
    assert 'from(bucket: "metrics")' in query
    assert "|> range(start: -1h, stop: now())" in query
    assert 'r._measurement == "system_metrics"' in query
    assert 'r._field == "cpu_usage"' in query


def test_query_data_formats_rfc3339_range_values() -> None:
    interface, query_api = _build_interface()

    interface.query_data(
        measurement="system_metrics",
        start="2026-02-24T10:00:00Z",
        stop="2026-02-24T11:00:00Z",
        field="cpu_usage",
    )

    query, _org = query_api.calls[0]
    assert 'time(v: "2026-02-24T10:00:00Z")' in query
    assert 'time(v: "2026-02-24T11:00:00Z")' in query


def test_query_data_rejects_injected_identifiers() -> None:
    interface, _query_api = _build_interface()

    with pytest.raises(InfluxDBQueryError):
        interface.query_data(
            measurement='system_metrics" |> drop()',
            start="-1h",
            stop="now()",
            field="cpu_usage",
        )


def test_get_available_fields_rejects_injected_measurement() -> None:
    interface, _query_api = _build_interface()

    with pytest.raises(InfluxDBQueryError):
        interface.get_available_fields('system_metrics" |> drop()')


def test_write_data_retries_and_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    interface, _query_api = _build_interface()
    write_api = _WriteAPIStub(failures_before_success=2)
    interface._write_api = cast(Any, write_api)
    sleeps: list[float] = []
    monkeypatch.setattr(
        influx_module.time, "sleep", lambda seconds: sleeps.append(seconds)
    )

    interface.write_data("system_metrics", {"cpu_usage": 12.5})

    assert write_api.calls == 3
    assert sleeps == [0.25, 0.5]


def test_write_data_raises_after_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    interface, _query_api = _build_interface()
    write_api = _WriteAPIStub(failures_before_success=10)
    interface._write_api = cast(Any, write_api)
    sleeps: list[float] = []
    monkeypatch.setattr(
        influx_module.time, "sleep", lambda seconds: sleeps.append(seconds)
    )

    with pytest.raises(InfluxDBWriteError):
        interface.write_data("system_metrics", {"cpu_usage": 12.5})

    assert write_api.calls == 3
    assert sleeps == [0.25, 0.5]
