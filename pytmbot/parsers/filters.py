from datetime import datetime


def format_timestamp(value: str or int) -> str:
    """
    Format a timestamp (either string or integer) into a human-readable string.

    Args:
        value (str or int): Timestamp in ISO 8601 string format or in seconds (integer).

    Returns:
        str: Formatted timestamp as a string in the format '%d-%m-%Y %H:%M:%S'.
    """
    if isinstance(value, str):
        try:
            dt = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ")
        except ValueError:
            dt = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    elif isinstance(value, int):
        dt = datetime.fromtimestamp(value / 1000)
    else:
        raise TypeError("Unsupported type for timestamp. Expected str or int.")

    return dt.strftime("%d-%m-%Y %H:%M:%S")
