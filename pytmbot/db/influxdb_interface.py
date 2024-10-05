import re
import socket
from datetime import datetime
from typing import List, Tuple, Optional
from urllib.parse import urlparse

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.exceptions import InfluxDBError
from influxdb_client.client.write_api import SYNCHRONOUS

from pytmbot.logs import bot_logger
from pytmbot.settings import settings


class InfluxDBInterface:
    """A class for interacting with InfluxDB for storing and retrieving monitoring data."""

    def __init__(self, url: str, token: str, org: str, bucket: str) -> None:
        """
        Initialize the InfluxDB interface.

        Args:
            url (str): The InfluxDB server URL.
            token (str): Authentication token for InfluxDB.
            org (str): Organization in InfluxDB.
            bucket (str): Bucket to store data in.
        """
        self.url = url
        self.token = token
        self.org = org
        self.bucket = bucket
        self.client = None
        self.write_api = None
        self.query_api = None
        self.debug_mode = settings.influxdb.debug_mode
        self.warning_showed = False

        if not self.check_url() and not self.warning_showed:
            self.warning_showed = True
            bot_logger.warning(f"Using non-local InfluxDB URL: {self.url}. Make sure is it secure.")

        if self.debug_mode:
            bot_logger.debug(f"InfluxDB client initialized with URL: {self.url}")

    def __enter__(self):
        """Enter the runtime context related to this object."""
        self.client = InfluxDBClient(url=self.url, token=self.token, org=self.org)
        self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
        self.query_api = self.client.query_api()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """
        Exit the runtime context related to this object.
        Closes the InfluxDB client connection.
        """
        if self.client:
            self.client.close()
            if self.debug_mode:
                bot_logger.debug("InfluxDB client successfully closed.")

    def check_url(self) -> bool:
        """
        Check if the InfluxDB URL is local.

        Returns:
            bool: True if the URL is local, False otherwise.
        """
        parsed_url = urlparse(self.url)
        hostname = parsed_url.hostname

        if hostname in ["localhost", "127.0.0.1"]:
            return True

        # Check if it's a private IP address
        try:
            ip = socket.gethostbyname(hostname)
            bot_logger.debug(f"Resolved IP for {hostname}: {ip}")

            # Match private IP ranges
            private_ip_patterns = [
                re.compile(r"^10\.\d{1,3}\.\d{1,3}\.\d{1,3}$"),  # 10.x.x.x
                re.compile(r"^192\.168\.\d{1,3}\.\d{1,3}$"),  # 192.168.x.x
                re.compile(r"^172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}$"),  # 172.16.x.x - 172.31.x.x
            ]

            for pattern in private_ip_patterns:
                if pattern.match(ip):
                    return True
        except socket.gaierror:
            bot_logger.warning(f"Failed to resolve hostname: {hostname}")

        return False

    def write_data(self, measurement: str, fields: dict[str, float], tags: Optional[dict[str, str]] = None) -> None:
        try:
            point = Point(measurement)

            if tags:
                for key, value in tags.items():
                    point = point.tag(key, value)

            for key, value in fields.items():
                point = point.field(key, value)

            point = point.time(datetime.now())
            if self.debug_mode:
                bot_logger.debug(f"Writing data to InfluxDB: measurement={measurement}, fields={fields}, tags={tags}")
            self.write_api.write(bucket=self.bucket, record=point)
        except InfluxDBError as e:
            bot_logger.error(f"Error writing to InfluxDB: {e}")
            raise

    def query_data(self, measurement: str, start: str, stop: str, field: str) -> List[Tuple[datetime, float]]:
        """
        Query data from InfluxDB for a specific measurement and time range.

        Args:
            measurement (str): The name of the measurement to query.
            start (str): Start time in RFC3339 format (e.g., "2023-09-01T00:00:00Z").
            stop (str): Stop time in RFC3339 format (e.g., "2023-09-01T23:59:59Z").
            field (str): The field key to query (e.g., "cpu").

        Returns:
            List[Tuple[datetime, float]]: List of timestamp and field value tuples.
        """
        try:
            query = (
                f'from(bucket: "{self.bucket}") '
                f'|> range(start: {start}, stop: {stop}) '
                f'|> filter(fn: (r) => r._measurement == "{measurement}") '
                f'|> filter(fn: (r) => r._field == "{field}") '
                f'|> yield(name: "mean")'
            )

            if self.debug_mode:
                bot_logger.debug(f"Running query: {query}")
            tables = self.query_api.query(query, org=self.org)
            results = []

            for table in tables:
                for record in table.records:
                    results.append((record.get_time(), record.get_value()))

            bot_logger.info(f"Query returned {len(results)} records from InfluxDB.")
            return results
        except InfluxDBError as e:
            bot_logger.error(f"Error querying InfluxDB: {e}")
            return []
