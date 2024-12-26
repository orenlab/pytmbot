from datetime import datetime
from typing import Union

from dateutil import parser


def format_timestamp(value: Union[str, int]) -> str:
    """
    Format a timestamp (either ISO 8601 string or integer in milliseconds)
    into a human-readable string.

    Args:
        value (Union[str, int]): Timestamp in ISO 8601 format or integer (milliseconds).

    Returns:
        str: Formatted timestamp as '%d-%m-%Y %H:%M:%S'.
    """
    if isinstance(value, str):
        try:
            dt = parser.isoparse(value)
        except ValueError:
            raise ValueError("Invalid string format for timestamp.")
    elif isinstance(value, int):
        dt = datetime.fromtimestamp(value / 1000)
    else:
        raise TypeError("Unsupported type for timestamp. Expected str or int.")

    return dt.strftime("%d-%m-%Y %H:%M:%S")
