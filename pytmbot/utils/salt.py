#!/usr/local/bin/python3
"""
(c) Copyright 2025, Denis Rozhnovskiy <pytelemonbot@mail.ru>
pyTMBot - A simple Telegram bot to handle Docker containers and images,
also providing basic information about the status of local servers.
"""

import base64
import secrets
from typing import Final

# Constants
DEFAULT_SALT_LENGTH: Final[int] = 32
MIN_SALT_LENGTH: Final[int] = 16
MAX_SALT_LENGTH: Final[int] = 64


def validate_salt_length(length: int) -> None:
    """
    Validates the salt length parameter.

    Args:
        length: The length to validate.

    Raises:
        ValueError: If length is not within acceptable bounds.
        TypeError: If length is not an integer.
    """
    if not isinstance(length, int):
        raise TypeError("Salt length must be an integer")

    if not MIN_SALT_LENGTH <= length <= MAX_SALT_LENGTH:
        raise ValueError(
            f"Salt length must be between {MIN_SALT_LENGTH} and {MAX_SALT_LENGTH} bytes"
        )


def generate_random_auth_salt(length: int = DEFAULT_SALT_LENGTH) -> str:
    """
    Generates a random authentication salt using cryptographically secure methods.

    Args:
        length: The length of the salt in bytes. Defaults to 32.

    Returns:
        A base32 encoded string representation of the salt.

    Raises:
        ValueError: If length is not within acceptable bounds.
        TypeError: If length is not an integer.
    """
    validate_salt_length(length)

    random_bytes = secrets.token_bytes(length)
    return base64.b32encode(random_bytes).decode("ascii")


def main() -> None:
    """Generate and print a random authentication salt."""
    try:
        salt = generate_random_auth_salt()
        print("=" * 56)
        print("Generating random authentication salt...")
        print(salt)
    except (ValueError, TypeError) as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
