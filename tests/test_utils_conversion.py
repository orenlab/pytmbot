from __future__ import annotations

import pytest

from pytmbot.utils.conversion import as_object_dict, to_float, to_float_strict, to_int


def test_as_object_dict_returns_dict_or_empty() -> None:
    assert as_object_dict({"a": 1}) == {"a": 1}
    assert as_object_dict([1, 2, 3]) == {}


def test_to_float_handles_numeric_and_percent_values() -> None:
    assert to_float(True) == 1.0
    assert to_float("  42.5  ") == 42.5
    assert to_float(" 42.5% ", strip_percent=True) == 42.5
    assert to_float("bad", default=3.5) == 3.5


def test_to_int_handles_strict_and_lenient_modes() -> None:
    assert to_int(True) == 1
    assert to_int(" 12 ") == 12
    assert to_int("12.8") == 0
    assert to_int("12.8", allow_float_string=True) == 12
    assert to_int("75%", strip_percent=True) == 75
    assert to_int("bad", default=7) == 7


def test_to_float_strict_raises_for_unsupported_types() -> None:
    assert to_float_strict(" 2.5 ") == 2.5
    with pytest.raises(TypeError):
        to_float_strict(object())
