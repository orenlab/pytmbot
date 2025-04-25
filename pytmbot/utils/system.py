import sys


def check_python_version(min_version: float) -> bool:
    """
    Checks if the current Python version meets the specified minimum version.
    """
    if not (isinstance(min_version, (float, int)) and min_version > 0):
        raise ValueError("min_version must be a positive float, e.g., 3.10.")

    # Convert the current Python version to a float (e.g., 3.10)
    current_version = float(f"{sys.version_info.major}.{sys.version_info.minor}")
    return current_version >= min_version
