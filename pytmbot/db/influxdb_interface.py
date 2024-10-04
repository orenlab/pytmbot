from datetime import datetime
from typing import List, Tuple, Optional

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
        self.bot_logger = bot_logger

    def __enter__(self):
        """
        Enter the runtime context related to this object.
        Opens the InfluxDB client connection.
        """
        self.client = InfluxDBClient(url=self.url, token=self.token, org=self.org)
        self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
        self.query_api = self.client.query_api()
        self.debug_mode = settings.influxdb.debug_mode
        if self.debug_mode:
            self.bot_logger.debug(f"InfluxDB client initialized with URL: {self.url}")
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        """
        Exit the runtime context related to this object.
        Closes the InfluxDB client connection.
        """
        if self.client:
            self.client.close()
            if self.debug_mode:
                self.bot_logger.debug("InfluxDB client successfully closed.")

    def write_data(self, measurement: str, fields: dict[str, float], tags: Optional[dict[str, str]] = None) -> None:
        try:
            point = Point(measurement)

            # Add tags if provided
            if tags:
                for key, value in tags.items():
                    point = point.tag(key, value)

            # Add field values
            for key, value in fields.items():
                point = point.field(key, value)

            point = point.time(datetime.now())
            if self.debug_mode:
                self.bot_logger.debug(
                    f"Writing data to InfluxDB: measurement={measurement}, fields={fields}, tags={tags}")
            self.write_api.write(bucket=self.bucket, record=point)
        except InfluxDBError as e:
            self.bot_logger.error(f"Error writing to InfluxDB: {e}")
            exit(2)

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
                self.bot_logger.debug(f"Running query: {query}")
            tables = self.query_api.query(query, org=self.org)
            results = []

            for table in tables:
                for record in table.records:
                    results.append((record.get_time(), record.get_value()))

            self.bot_logger.info(f"Query returned {len(results)} records from InfluxDB.")
            return results
        except InfluxDBError as e:
            self.bot_logger.error(f"Error querying InfluxDB: {e}")
