from __future__ import annotations

import concurrent.futures
from collections.abc import Callable
from dataclasses import dataclass
from types import MethodType
from typing import cast

import pytest
from influxdb_client.client.query_api import QueryApi
from influxdb_client.client.write_api import WriteApi

from pytmbot.db.influxdb_interface import InfluxDBConfig, InfluxDBInterface
from pytmbot.exceptions import (
    InfluxDBConnectionError,
    InfluxDBQueryError,
    InfluxDBWriteError,
)

type _RecordScalar = str | int | float | bool | None
type _Record = dict[str, _RecordScalar]


@dataclass
class _QueryAPIStub:
    calls: list[tuple[str, str]]

    def query(self, query: str, org: str) -> list[_Record]:
        self.calls.append((query, org))
        return []


@dataclass
class _WriteAPIStub:
    failures_before_success: int
    calls: int = 0

    def write(self, bucket: str, record: _Record | str) -> None:
        del bucket, record
        self.calls += 1
        if self.calls <= self.failures_before_success:
            raise RuntimeError("temporary write failure")


@dataclass
class _ImmediateExecutorStub:
    def submit(self, func: Callable[[], None]) -> None:
        func()


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
    interface._query_api = cast(QueryApi, query_api)
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
    interface._write_api = cast(WriteApi, write_api)
    sleeps: list[float] = []
    monkeypatch.setattr(
        "pytmbot.db.influxdb_interface.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    interface.write_data("system_metrics", {"cpu_usage": 12.5})

    assert write_api.calls == 3
    assert sleeps == [0.25, 0.5]


def test_write_data_raises_after_max_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    interface, _query_api = _build_interface()
    write_api = _WriteAPIStub(failures_before_success=10)
    interface._write_api = cast(WriteApi, write_api)
    sleeps: list[float] = []
    monkeypatch.setattr(
        "pytmbot.db.influxdb_interface.time.sleep",
        lambda seconds: sleeps.append(seconds),
    )

    with pytest.raises(InfluxDBWriteError):
        interface.write_data("system_metrics", {"cpu_usage": 12.5})

    assert write_api.calls == 3
    assert sleeps == [0.25, 0.5]


def test_write_data_async_submits_task(monkeypatch: pytest.MonkeyPatch) -> None:
    interface, _query_api = _build_interface()
    interface._async_write_executor = cast(
        concurrent.futures.ThreadPoolExecutor,
        _ImmediateExecutorStub(),
    )

    calls: list[tuple[str, dict[str, float], dict[str, str] | None]] = []

    def _fake_write_data(
        self: InfluxDBInterface,
        measurement: str,
        fields: dict[str, float],
        tags: dict[str, str] | None = None,
    ) -> None:
        calls.append((measurement, dict(fields), dict(tags) if tags else None))

    monkeypatch.setattr(
        interface,
        "write_data",
        MethodType(_fake_write_data, interface),
    )

    submitted = interface.write_data_async(
        "system_metrics",
        {"cpu_usage": 12.5},
        {"host": "local"},
    )

    assert submitted is True
    assert calls == [("system_metrics", {"cpu_usage": 12.5}, {"host": "local"})]


def test_write_data_async_returns_false_when_queue_is_full() -> None:
    interface, _query_api = _build_interface()

    for _ in range(interface._ASYNC_WRITE_MAX_PENDING_TASKS):
        assert interface._async_write_slots.acquire(blocking=False)

    try:
        submitted = interface.write_data_async("system_metrics", {"cpu_usage": 12.5})
        assert submitted is False
    finally:
        for _ in range(interface._ASYNC_WRITE_MAX_PENDING_TASKS):
            interface._async_write_slots.release()


def test_connect_failure_uses_safe_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        InfluxDBInterface,
        "_resolve_hostname",
        staticmethod(lambda _hostname: "8.8.8.8"),
    )
    interface = InfluxDBInterface(
        InfluxDBConfig(
            url="https://influx.example:8086",
            token="secret-token",
            org="secret-org",
            bucket="secret-bucket",
            debug_mode=False,
        )
    )

    def _raise_client_factory(**_kwargs: object) -> object:
        raise RuntimeError(
            "failed to reach https://influx.example:8086 with secret-token"
        )

    monkeypatch.setattr(
        "pytmbot.db.influxdb_interface.InfluxDBClient",
        _raise_client_factory,
    )

    with pytest.raises(InfluxDBConnectionError) as exc_info:
        interface.connect()

    metadata = exc_info.value.context.metadata
    assert metadata == {
        "url_present": True,
        "token_present": True,
        "org_present": True,
        "bucket_present": True,
        "debug_mode": False,
    }
    assert "https://influx.example:8086" not in str(metadata)
    assert "secret-token" not in str(metadata)
