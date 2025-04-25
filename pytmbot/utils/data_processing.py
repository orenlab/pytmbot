from datetime import datetime
from typing import Any, Dict, Tuple, Optional

from humanize import naturalsize as humanize_naturalsize, naturaltime as humanize_naturaltime


def round_up_tuple(numbers: Tuple[float, ...]) -> Dict[int, float]:
    return {i: round(num, 2) for i, num in enumerate(numbers)}


def find_in_args(args: Tuple[Any, ...], target_type: type) -> Optional[Any]:
    return next((arg for arg in args if isinstance(arg, target_type)), None)


def find_in_kwargs(kwargs: Dict[str, Any], target_type: type) -> Optional[Any]:
    return next((value for value in kwargs.values() if isinstance(value, target_type)), None)


def set_naturalsize(size: int) -> str:
    return humanize_naturalsize(size, binary=True)


def set_naturaltime(timestamp: datetime) -> str:
    return humanize_naturaltime(timestamp)


def split_string_into_octets(input_string: str, delimiter: str = ":", octet_index: int = 1) -> str:
    octets = input_string.split(delimiter)
    if not (0 <= octet_index < len(octets)):
        raise IndexError("Octet index out of range")
    return octets[octet_index].lower()
