from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pytmbot.utils.data_processing import (
    round_up_tuple,
    set_naturalsize,
    set_naturaltime,
    split_string_into_octets,
)


def test_round_up_tuple_returns_indexed_mapping() -> None:
    result = round_up_tuple((1.234, 5.678, 9.0))
    assert result == {0: 1.23, 1: 5.68, 2: 9.0}


def test_set_naturalsize_and_naturaltime_return_strings() -> None:
    assert "KiB" in set_naturalsize(2048)
    assert set_naturalsize(None) == "0 Bytes"
    assert set_naturalsize(-1) == "0 Bytes"
    with pytest.raises(TypeError):
        set_naturalsize("bad")  # type: ignore[arg-type]
    assert isinstance(set_naturaltime(datetime.now(UTC)), str)


def test_split_string_into_octets_returns_lowercase_slice() -> None:
    assert split_string_into_octets("__op__:PyTMBot:123", octet_index=1) == "pytmbot"


def test_split_string_into_octets_raises_for_invalid_index() -> None:
    with pytest.raises(IndexError):
        split_string_into_octets("a:b", octet_index=5)


def test_split_string_into_octets_validates_inputs() -> None:
    with pytest.raises(ValueError):
        split_string_into_octets("")
    with pytest.raises(ValueError):
        split_string_into_octets("a:b", delimiter="")
