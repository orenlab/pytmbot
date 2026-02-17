from __future__ import annotations

import re

import pytest

from pytmbot.utils.salt import (
    DEFAULT_SALT_LENGTH,
    MAX_SALT_LENGTH,
    MIN_SALT_LENGTH,
    generate_random_auth_salt,
    validate_salt_length,
)


def test_validate_salt_length_accepts_bounds() -> None:
    validate_salt_length(MIN_SALT_LENGTH)
    validate_salt_length(DEFAULT_SALT_LENGTH)
    validate_salt_length(MAX_SALT_LENGTH)


def test_validate_salt_length_rejects_invalid_values() -> None:
    with pytest.raises(TypeError):
        validate_salt_length("32")  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        validate_salt_length(MIN_SALT_LENGTH - 1)
    with pytest.raises(ValueError):
        validate_salt_length(MAX_SALT_LENGTH + 1)


def test_generate_random_auth_salt_returns_base32_ascii() -> None:
    salt = generate_random_auth_salt(16)
    assert isinstance(salt, str)
    assert re.fullmatch(r"[A-Z2-7]+=*", salt) is not None
