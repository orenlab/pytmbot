from datetime import datetime


def format_timestamp(value: int) -> str:
    """
    Format a timestamp from Docker into a human-readable string.

    Args:
        value (int): Timestamp in milliseconds.

    Returns:
        str: Timestamp as a string in the format '%d-%m-%Y %H:%M:%S'.
    """
    return datetime.fromtimestamp(value / 1000).strftime('%d-%m-%Y %H:%M:%S')
