#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import ipaddress
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from urllib.parse import urlparse

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

from pytmbot.exceptions import (
    ErrorContext,
    InfluxDBConfigError,
    InfluxDBConnectionError,
    InfluxDBQueryError,
    InfluxDBWriteError,
)
from pytmbot.logs import BaseComponent


@dataclass(frozen=True, slots=True)
class InfluxDBConfig:
    """Configuration for InfluxDB connection."""

    url: str
    token: str
    org: str
    bucket: str
    debug_mode: bool = False


class InfluxDBInterface(BaseComponent):
    """A class for interacting with InfluxDB for storing and retrieving monitoring data."""

    _FLUX_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
    _FLUX_DURATION_PATTERN = re.compile(r"^-?\d+(ns|us|ms|s|m|h|d|w|mo|y)$")
    _WRITE_RETRY_ATTEMPTS = 3
    _WRITE_RETRY_BASE_BACKOFF_SECONDS = 0.25

    def __init__(self, config: InfluxDBConfig) -> None:
        """
        Initialize the InfluxDB interface.

        Args:
            config (InfluxDBConfig): Configuration dataclass containing connection details

        Raises:
            InfluxDBConfigError: If configuration validation fails
        """
        super().__init__("InfluxDBInterface")
        self._config = config
        self._client: InfluxDBClient | None = None
        self._write_api = None
        self._query_api = None
        self._warning_shown = False
        self._initialized = False

        # Validate configuration only once during initialization
        try:
            if not all([config.url, config.token, config.org, config.bucket]):
                raise InfluxDBConfigError(
                    ErrorContext(
                        message="Invalid InfluxDB configuration",
                        error_code="INVALID_CONFIG",
                        metadata={
                            "url": bool(config.url),
                            "token": bool(config.token),
                            "org": bool(config.org),
                            "bucket": bool(config.bucket),
                        },
                    )
                )

            # Show non-local URL warning only once
            if not self._is_local_url() and not self._warning_shown:
                self._warning_shown = True
                with self.log_context(action="initialization") as log:
                    log.warning(
                        "bot.db.influxdb_interface.using.non.warn",
                        extra={"url": self._config.url},
                    )

            # Log initialization only once and only in debug mode
            if self._config.debug_mode:
                with self.log_context(action="initialization") as log:
                    log.debug(
                        "bot.db.influxdb_interface.influx.client.init",
                        extra={
                            "url": self._config.url,
                            "org": self._config.org,
                            "bucket": self._config.bucket,
                        },
                    )

        except Exception as e:
            error_context = ErrorContext(
                message=f"InfluxDB initialization failed: {str(e)}",
                error_code="INIT_FAILED",
                metadata={"url": self._config.url},
            )
            raise InfluxDBConfigError(error_context) from e

    def __enter__(self) -> "InfluxDBInterface":
        """Enter the runtime context and initialize the client connection."""
        try:
            self._client = InfluxDBClient(
                url=self._config.url, token=self._config.token, org=self._config.org
            )
            self._write_api = self._client.write_api(write_options=SYNCHRONOUS)
            self._query_api = self._client.query_api()

            # Log connection only once or in debug mode
            if not self._initialized or self._config.debug_mode:
                with self.log_context(action="connect") as log:
                    log.debug("bot.db.influxdb_interface.influx.connection.debug")
                self._initialized = True

            return self

        except Exception as e:
            error_context = ErrorContext(
                message=f"Failed to establish InfluxDB connection: {str(e)}",
                error_code="CONNECTION_FAILED",
                metadata={"url": self._config.url, "org": self._config.org},
            )
            raise InfluxDBConnectionError(error_context) from e

    def _require_write_api(self) -> Any:
        """Return initialized write API or raise connection error."""
        if self._write_api is None:
            raise InfluxDBConnectionError(
                ErrorContext(
                    message="InfluxDB write API is not initialized",
                    error_code="WRITE_API_NOT_INITIALIZED",
                )
            )
        return self._write_api

    def _require_query_api(self) -> Any:
        """Return initialized query API or raise connection error."""
        if self._query_api is None:
            raise InfluxDBConnectionError(
                ErrorContext(
                    message="InfluxDB query API is not initialized",
                    error_code="QUERY_API_NOT_INITIALIZED",
                )
            )
        return self._query_api

    @staticmethod
    def _to_flux_string_literal(value: str) -> str:
        """Return safe Flux string literal."""
        return json.dumps(value)

    def _sanitize_flux_identifier(self, value: str, field_name: str) -> str:
        """Validate identifier-like value to prevent Flux injection."""
        if not isinstance(value, str):
            raise ValueError(f"{field_name} must be a string")

        candidate = value.strip()
        if not candidate:
            raise ValueError(f"{field_name} cannot be empty")

        if not self._FLUX_IDENTIFIER_PATTERN.fullmatch(candidate):
            raise ValueError(f"Invalid {field_name} format")

        return candidate

    def _sanitize_flux_range_value(self, value: str, field_name: str) -> str:
        """Validate and format Flux range values."""
        if not isinstance(value, str):
            raise ValueError(f"{field_name} must be a string")

        candidate = value.strip()
        if not candidate:
            raise ValueError(f"{field_name} cannot be empty")

        if candidate == "now()":
            return candidate

        if self._FLUX_DURATION_PATTERN.fullmatch(candidate):
            return candidate

        normalized = candidate.replace("Z", "+00:00")
        try:
            parsed_dt = datetime.fromisoformat(normalized)
        except ValueError as error:
            raise ValueError(f"Invalid {field_name} value") from error

        if parsed_dt.tzinfo is None:
            parsed_dt = parsed_dt.replace(tzinfo=UTC)
        else:
            parsed_dt = parsed_dt.astimezone(UTC)

        iso_value = parsed_dt.isoformat().replace("+00:00", "Z")
        return f'time(v: "{iso_value}")'

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit the runtime context and ensure proper cleanup."""
        if self._client:
            try:
                self._client.close()
                self._client = None
                self._write_api = None
                self._query_api = None

                # Log disconnect only in debug mode
                if self._config.debug_mode:
                    with self.log_context(action="disconnect") as log:
                        log.debug("bot.db.influxdb_interface.influx.connection.ok")

            except Exception as e:
                error_context = ErrorContext(
                    message=f"Error closing InfluxDB connection: {str(e)}",
                    error_code="DISCONNECT_FAILED",
                )
                raise InfluxDBConnectionError(error_context) from e

    @lru_cache(maxsize=128)
    def _is_local_url(self) -> bool:
        """
        Check if the InfluxDB URL is local using cached results.

        Returns:
            bool: True if the URL is local, False otherwise
        """
        parsed_url = urlparse(self._config.url)
        hostname = parsed_url.hostname
        if hostname is None:
            return False

        if hostname in ("localhost", "127.0.0.1"):
            return True

        try:
            ip_addr = ipaddress.ip_address(hostname)
            is_private = ip_addr.is_private

            # Log IP check only in debug mode
            if self._config.debug_mode:
                with self.log_context(action="check_url") as log:
                    log.debug(
                        "bot.db.influxdb_interface.ip.address.debug",
                        extra={"hostname": hostname, "is_private": is_private},
                    )
            return is_private

        except ValueError:
            try:
                ip_str = str(ipaddress.ip_address(self._resolve_hostname(hostname)))
                is_private = ipaddress.ip_address(ip_str).is_private

                # Log hostname resolution only in debug mode
                if self._config.debug_mode:
                    with self.log_context(action="check_url") as log:
                        log.debug(
                            "bot.db.influxdb_interface.hostname.resolved.debug",
                            extra={
                                "hostname": hostname,
                                "ip": ip_str,
                                "is_private": is_private,
                            },
                        )
                return is_private

            except ValueError:
                # Warning about hostname resolution failure - shown only once
                if not self._warning_shown:
                    with self.log_context(action="check_url") as log:
                        log.warning(
                            "bot.db.influxdb_interface.resolve.hostname.fail",
                            extra={"hostname": hostname},
                        )
                return False

    @staticmethod
    @lru_cache(maxsize=128)
    def _resolve_hostname(hostname: str) -> str:
        """
        Resolve hostname to IP address with caching.

        Args:
            hostname: The hostname to resolve

        Returns:
            str: The resolved IP address
        """
        import socket

        return socket.gethostbyname(hostname)

    def write_data(
        self,
        measurement: str,
        fields: dict[str, float],
        tags: dict[str, str] | None = None,
    ) -> None:
        """
        Write data points to InfluxDB.

        Args:
            measurement: The measurement name
            fields: Dictionary of field names and values
            tags: Optional dictionary of tags

        Raises:
            InfluxDBWriteError: If write operation fails
        """
        try:
            point = Point(measurement).time(datetime.now(UTC))

            if tags:
                for tag_key, tag_value in tags.items():
                    point = point.tag(tag_key, tag_value)

            for field_key, field_value in fields.items():
                point = point.field(field_key, field_value)

            # Log write operations only in debug mode to avoid noise
            if self._config.debug_mode:
                with self.log_context(
                    action="write",
                    measurement=measurement,
                    field_count=len(fields),
                    tag_count=len(tags) if tags else 0,
                ) as log:
                    log.debug(
                        "bot.db.influxdb_interface.writing.data.debug",
                        extra={
                            "measurement": measurement,
                            "fields": fields,
                            "tags": tags,
                        },
                    )

            write_api = self._require_write_api()
            for attempt in range(self._WRITE_RETRY_ATTEMPTS):
                try:
                    write_api.write(bucket=self._config.bucket, record=point)
                    break
                except Exception:
                    if attempt >= self._WRITE_RETRY_ATTEMPTS - 1:
                        raise
                    backoff_seconds = self._WRITE_RETRY_BASE_BACKOFF_SECONDS * (
                        2**attempt
                    )
                    with self.log_context(
                        action="write_retry",
                        retry_attempt=attempt + 1,
                        max_attempts=self._WRITE_RETRY_ATTEMPTS,
                        backoff_seconds=backoff_seconds,
                    ) as log:
                        log.warning("bot.db.influxdb_interface.write.retry.warn")
                    time.sleep(backoff_seconds)

            # Success logging only in debug mode
            if self._config.debug_mode:
                with self.log_context(action="write") as log:
                    log.debug("bot.db.influxdb_interface.data.point.ok")

        except Exception as e:
            # Always log errors
            error_context = ErrorContext(
                message=f"Failed to write data point: {str(e)}",
                error_code="WRITE_FAILED",
                metadata={
                    "measurement": measurement,
                    "field_count": len(fields),
                    "tag_count": len(tags) if tags else 0,
                },
            )
            raise InfluxDBWriteError(error_context) from e

    def query_data(
        self, measurement: str, start: str, stop: str, field: str
    ) -> list[tuple[datetime, float]]:
        """
        Query data from InfluxDB for a specific measurement and time range.

        Args:
            measurement: The measurement name
            start: Start time in RFC3339 format
            stop: Stop time in RFC3339 format
            field: The field key to query

        Returns:
            List of timestamp and value tuples

        Raises:
            InfluxDBQueryError: If query operation fails
        """
        try:
            safe_bucket = self._sanitize_flux_identifier(self._config.bucket, "bucket")
            safe_measurement = self._sanitize_flux_identifier(
                measurement, "measurement"
            )
            safe_field = self._sanitize_flux_identifier(field, "field")
            safe_start = self._sanitize_flux_range_value(start, "start")
            safe_stop = self._sanitize_flux_range_value(stop, "stop")

            query = (
                f"from(bucket: {self._to_flux_string_literal(safe_bucket)}) "
                f"|> range(start: {safe_start}, stop: {safe_stop}) "
                f"|> filter(fn: (r) => r._measurement == "
                f"{self._to_flux_string_literal(safe_measurement)}) "
                f"|> filter(fn: (r) => r._field == "
                f"{self._to_flux_string_literal(safe_field)}) "
                f'|> yield(name: "mean")'
            )

            # Log query execution only in debug mode
            if self._config.debug_mode:
                with self.log_context(
                    action="query",
                    measurement=safe_measurement,
                    field=safe_field,
                    time_range={"start": safe_start, "stop": safe_stop},
                ) as log:
                    log.debug(
                        "bot.db.influxdb_interface.exec.query.debug",
                        extra={"query": query},
                    )

            query_api = self._require_query_api()
            tables = query_api.query(query, org=self._config.org)

            results = [
                (record.get_time(), record.get_value())
                for table in tables
                for record in table.records
            ]

            # Log successful query only in debug mode
            if self._config.debug_mode:
                with self.log_context(action="query") as log:
                    log.debug(
                        "bot.db.influxdb_interface.query.executed.ok",
                        extra={"record_count": len(results)},
                    )

            return results

        except Exception as e:
            # Always log query errors
            error_context = ErrorContext(
                message=f"Query execution failed: {str(e)}",
                error_code="QUERY_FAILED",
                metadata={
                    "measurement": measurement,
                    "field": field,
                    "time_range": {"start": start, "stop": stop},
                },
            )
            raise InfluxDBQueryError(error_context) from e

    @lru_cache(maxsize=32)
    def get_available_measurements(self) -> list[str]:
        """
        Retrieve available measurements from InfluxDB with caching.

        Returns:
            List of measurement names

        Raises:
            InfluxDBQueryError: If retrieval fails
        """
        try:
            safe_bucket = self._sanitize_flux_identifier(self._config.bucket, "bucket")
            query = (
                'import "influxdata/influxdb/schema"\n'
                f"schema.measurements(bucket: {self._to_flux_string_literal(safe_bucket)})"
            )

            # Log only in debug mode
            if self._config.debug_mode:
                with self.log_context(action="list_measurements") as log:
                    log.debug(
                        "bot.db.influxdb_interface.fetch.measurements.debug",
                        extra={"query": query},
                    )

            query_api = self._require_query_api()
            tables = query_api.query(query, org=self._config.org)

            measurements = [
                record.get_value() for table in tables for record in table.records
            ]

            # Log success only in debug mode
            if self._config.debug_mode:
                with self.log_context(action="list_measurements") as log:
                    log.debug(
                        "bot.db.influxdb_interface.measurements.fetch.ok",
                        extra={"count": len(measurements)},
                    )

            return measurements

        except Exception as e:
            # Always log errors
            error_context = ErrorContext(
                message=f"Failed to retrieve measurements: {str(e)}",
                error_code="LIST_MEASUREMENTS_FAILED",
            )
            raise InfluxDBQueryError(error_context) from e

    @lru_cache(maxsize=64)
    def get_available_fields(self, measurement: str) -> list[str]:
        """
        Retrieve available fields for a measurement with caching.

        Args:
            measurement: The measurement name

        Returns:
            List of field names

        Raises:
            InfluxDBQueryError: If retrieval fails
        """
        try:
            safe_bucket = self._sanitize_flux_identifier(self._config.bucket, "bucket")
            safe_measurement = self._sanitize_flux_identifier(
                measurement, "measurement"
            )
            query = (
                f"from(bucket: {self._to_flux_string_literal(safe_bucket)})"
                f"|> range(start: -1h)"
                f"|> filter(fn: (r) => r._measurement == "
                f"{self._to_flux_string_literal(safe_measurement)})"
                f'|> keep(columns: ["_field"])'
                f'|> distinct(column: "_field")'
                f'|> yield(name: "fields")'
            )

            # Log only in debug mode
            if self._config.debug_mode:
                with self.log_context(
                    action="list_fields", measurement=safe_measurement
                ) as log:
                    log.debug(
                        "bot.db.influxdb_interface.fetch.fields.debug",
                        extra={"query": query},
                    )

            query_api = self._require_query_api()
            tables = query_api.query(query, org=self._config.org)

            fields = [
                record.get_value() for table in tables for record in table.records
            ]

            # Log success only in debug mode
            if self._config.debug_mode:
                with self.log_context(
                    action="list_fields", measurement=safe_measurement
                ) as log:
                    log.debug(
                        "bot.db.influxdb_interface.fields.fetch.ok",
                        extra={
                            "measurement": safe_measurement,
                            "field_count": len(fields),
                        },
                    )

            return fields

        except Exception as e:
            # Always log errors
            error_context = ErrorContext(
                message=f"Failed to retrieve fields: {str(e)}",
                error_code="LIST_FIELDS_FAILED",
                metadata={"measurement": measurement},
            )
            raise InfluxDBQueryError(error_context) from e
