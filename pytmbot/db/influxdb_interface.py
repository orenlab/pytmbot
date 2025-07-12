#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import ipaddress
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from typing import List, Tuple, Optional, Dict, Any
from urllib.parse import urlparse

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS

from pytmbot.exceptions import (
    ErrorContext,
    InfluxDBConfigError,
    InfluxDBConnectionError,
    InfluxDBWriteError,
    InfluxDBQueryError,
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
        self._client: Optional[InfluxDBClient] = None
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
                        "Using non-local InfluxDB URL. Ensure it is secure.",
                        extra={"url": self._config.url},
                    )

            # Log initialization only once and only in debug mode
            if self._config.debug_mode:
                with self.log_context(action="initialization") as log:
                    log.debug(
                        "InfluxDB client initialized",
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
                    log.debug("InfluxDB connection established")
                self._initialized = True

            return self

        except Exception as e:
            error_context = ErrorContext(
                message=f"Failed to establish InfluxDB connection: {str(e)}",
                error_code="CONNECTION_FAILED",
                metadata={"url": self._config.url, "org": self._config.org},
            )
            raise InfluxDBConnectionError(error_context) from e

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
                        log.debug("InfluxDB connection closed successfully")

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

        if hostname in ("localhost", "127.0.0.1"):
            return True

        try:
            ip_addr = ipaddress.ip_address(hostname)
            is_private = ip_addr.is_private

            # Log IP check only in debug mode
            if self._config.debug_mode:
                with self.log_context(action="check_url") as log:
                    log.debug(
                        "IP address checked",
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
                            "Hostname resolved and checked",
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
                            "Failed to resolve hostname", extra={"hostname": hostname}
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
        fields: Dict[str, float],
        tags: Optional[Dict[str, str]] = None,
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
            point = Point(measurement).time(datetime.now(timezone.utc))

            if tags:
                for key, value in tags.items():
                    point = point.tag(key, value)

            for key, value in fields.items():
                point = point.field(key, value)

            # Log write operations only in debug mode to avoid noise
            if self._config.debug_mode:
                with self.log_context(
                    action="write",
                    measurement=measurement,
                    field_count=len(fields),
                    tag_count=len(tags) if tags else 0,
                ) as log:
                    log.debug(
                        "Writing data point",
                        extra={
                            "measurement": measurement,
                            "fields": fields,
                            "tags": tags,
                        },
                    )

            self._write_api.write(bucket=self._config.bucket, record=point)

            # Success logging only in debug mode
            if self._config.debug_mode:
                with self.log_context(action="write") as log:
                    log.debug("Data point written successfully")

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
    ) -> List[Tuple[datetime, float]]:
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
        query = (
            f'from(bucket: "{self._config.bucket}") '
            f"|> range(start: {start}, stop: {stop}) "
            f'|> filter(fn: (r) => r._measurement == "{measurement}") '
            f'|> filter(fn: (r) => r._field == "{field}") '
            f'|> yield(name: "mean")'
        )

        try:
            # Log query execution only in debug mode
            if self._config.debug_mode:
                with self.log_context(
                    action="query",
                    measurement=measurement,
                    field=field,
                    time_range={"start": start, "stop": stop},
                ) as log:
                    log.debug("Executing query", extra={"query": query})

            tables = self._query_api.query(query, org=self._config.org)

            results = [
                (record.get_time(), record.get_value())
                for table in tables
                for record in table.records
            ]

            # Log successful query only in debug mode
            if self._config.debug_mode:
                with self.log_context(action="query") as log:
                    log.debug(
                        "Query executed successfully",
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
    def get_available_measurements(self) -> List[str]:
        """
        Retrieve available measurements from InfluxDB with caching.

        Returns:
            List of measurement names

        Raises:
            InfluxDBQueryError: If retrieval fails
        """
        query = (
            'import "influxdata/influxdb/schema"\n'
            f'schema.measurements(bucket: "{self._config.bucket}")'
        )

        try:
            # Log only in debug mode
            if self._config.debug_mode:
                with self.log_context(action="list_measurements") as log:
                    log.debug("Fetching measurements", extra={"query": query})

            tables = self._query_api.query(query, org=self._config.org)

            measurements = [
                record.get_value() for table in tables for record in table.records
            ]

            # Log success only in debug mode
            if self._config.debug_mode:
                with self.log_context(action="list_measurements") as log:
                    log.debug(
                        "Measurements retrieved successfully",
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
    def get_available_fields(self, measurement: str) -> List[str]:
        """
        Retrieve available fields for a measurement with caching.

        Args:
            measurement: The measurement name

        Returns:
            List of field names

        Raises:
            InfluxDBQueryError: If retrieval fails
        """
        query = (
            f'from(bucket: "{self._config.bucket}")'
            f"|> range(start: -1h)"
            f'|> filter(fn: (r) => r._measurement == "{measurement}")'
            f'|> keep(columns: ["_field"])'
            f'|> distinct(column: "_field")'
            f'|> yield(name: "fields")'
        )

        try:
            # Log only in debug mode
            if self._config.debug_mode:
                with self.log_context(
                    action="list_fields", measurement=measurement
                ) as log:
                    log.debug("Fetching fields", extra={"query": query})

            tables = self._query_api.query(query, org=self._config.org)

            fields = [
                record.get_value() for table in tables for record in table.records
            ]

            # Log success only in debug mode
            if self._config.debug_mode:
                with self.log_context(
                    action="list_fields", measurement=measurement
                ) as log:
                    log.debug(
                        "Fields retrieved successfully",
                        extra={"measurement": measurement, "field_count": len(fields)},
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
