import argparse
import os
import re
import secrets
from datetime import datetime
from functools import cached_property, lru_cache
from typing import Any, Dict, Optional, Tuple, Union

from humanize import (
    naturalsize as humanize_naturalsize,
    naturaltime as humanize_naturaltime,
)
from telebot.types import CallbackQuery, Message

from pytmbot.settings import settings


# Utility functions


@lru_cache(maxsize=None)
def parse_cli_args() -> argparse.Namespace:
    """
    Parses command line arguments using `argparse`.

    Returns:
        argparse.Namespace: The parsed command line arguments.
    """
    parser = argparse.ArgumentParser(description="PyTMBot CLI")

    parser.add_argument(
        "--mode",
        choices=["dev", "prod"],
        default="prod",
        help="PyTMBot mode (dev or prod)",
    )

    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "ERROR"],
        default="INFO",
        help="Log level",
    )

    parser.add_argument(
        "--colorize_logs",
        choices=["True", "False"],
        default="True",
        help="Colorize logs",
    )

    parser.add_argument(
        "--webhook",
        choices=["True", "False"],
        default="False",
        help="Start in webhook mode",
    )

    parser.add_argument(
        "--socket_host",
        default="127.0.0.1",
        help="Socket host for listening in webhook mode",
    )

    parser.add_argument(
        "--plugins", nargs="+", default=[], help="List of plugins to load"
    )

    args = parser.parse_args()
    return args


def round_up_tuple(numbers: Tuple[float, ...]) -> Dict[int, float]:
    """
    Rounds up numbers in a tuple to two decimal places.

    Args:
        numbers (Tuple[float, ...]): The numbers to round up.

    Returns:
        Dict[int, float]: A dictionary mapping the index of each number to its rounded value.
    """
    rounded = {i: round(num, 2) for i, num in enumerate(numbers)}
    return rounded


def find_in_args(args: Tuple[Any, ...], target_type: type) -> Optional[Any]:
    """
    Finds the first occurrence of an argument of the specified type in a tuple.

    Args:
        args (Tuple[Any, ...]): The tuple to search in.
        target_type (type): The type of argument to search for.

    Returns:
        Optional[Any]: The first occurrence of an argument of the specified type, or None if not found.
    """
    return next((arg for arg in args if isinstance(arg, target_type)), None)


def find_in_kwargs(kwargs: Dict[str, Any], target_type: type) -> Optional[Any]:
    """
    Finds the first occurrence of an argument of the specified type in the values of a dictionary.

    Args:
        kwargs (Dict[str, Any]): The dictionary to search in.
        target_type (type): The type of argument to search for.

    Returns:
        Optional[Any]: The first occurrence of an argument of the specified type, or None if not found.
    """
    return next(
        (value for value in kwargs.values() if isinstance(value, target_type)), None
    )


def set_naturalsize(size: int) -> str:
    """
    Converts a size in bytes to a human-readable format.

    Args:
        size (int): The size in bytes.

    Returns:
        str: The size in a human-readable format.
    """
    return humanize_naturalsize(size, binary=True)


def set_naturaltime(timestamp: datetime) -> str:
    """
    Converts a timestamp to a human-readable format.

    Args:
        timestamp (datetime): The timestamp to convert.

    Returns:
        str: The timestamp in a human-readable format.
    """
    return humanize_naturaltime(timestamp)


class EmojiConverter:
    """
    Converts emoji names to emoji characters.
    """

    @cached_property
    def emoji_library(self) -> Any:
        """
        Returns the emoji library module.

        Returns:
            Any: The emoji library module.
        """
        return __import__("emoji")

    def get_emoji(self, emoji_name: str) -> str:
        """
        Retrieves the emoji character corresponding to the given emoji name.

        Args:
            emoji_name (str): The name of the emoji to retrieve.

        Returns:
            str: The emoji character corresponding to the given emoji name.
        """
        emoji_str = f":{emoji_name}:"
        return self.emoji_library.emojize(emoji_str)


def split_string_into_octets(
        input_string: str, delimiter: str = ":", octet_index: int = 1
) -> str:
    """
    Extracts a specific octet from a string based on a delimiter.

    Args:
        input_string (str): The string to extract the octet from.
        delimiter (str): The delimiter used to split the string. Defaults to ":".
        octet_index (int): The index of the octet to extract. Defaults to 1.

    Returns:
        str: The extracted octet, converted to lowercase.

    Raises:
        IndexError: If the octet index is out of range.
    """
    octets = input_string.split(delimiter)
    if not (0 <= octet_index < len(octets)):
        raise IndexError("Octet index out of range")

    return octets[octet_index].lower()


def sanitize_logs(
        container_logs: Union[str, Any], callback_query: CallbackQuery, token: str
) -> str:
    """
    Sanitizes Docker container logs by replacing sensitive user information
    with asterisks and removing color codes.

    Args:
        container_logs (Union[str, Any]): The container logs.
        callback_query (CallbackQuery): The callback query object.
        token (str): The bot token.

    Returns:
        str: The sanitized logs.
    """
    ansi_escape = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")

    # Remove color codes
    container_logs = ansi_escape.sub("", container_logs)

    # User information for sanitization
    user_info = [
        callback_query.from_user.username or "",
        callback_query.from_user.first_name or "",
        callback_query.from_user.last_name or "",
        str(callback_query.message.from_user.id),
        token,
    ]

    # Replace sensitive information with asterisks
    for value in user_info:
        container_logs = container_logs.replace(value, "*" * len(value))

    return container_logs


def get_message_full_info(*args: Any, **kwargs: Any) -> Tuple[
    Union[str, None],
    Union[int, None],
    Union[str, None],
    Union[bool, None],
    Union[str, None],
]:
    """
    Retrieves full information for inline handlers logs.

    Args:
        *args (Any): Variable length argument list.
        **kwargs (Any): Arbitrary keyword arguments.

    Returns:
        Tuple[Union[str, None], Union[int, None], Union[str, None], Union[bool, None], Union[str, None]]:
            A tuple containing the username, user ID, language code, is_bot flag, and message text.
    """
    message = find_in_args(args, Message) or find_in_kwargs(kwargs, Message)
    if message:
        user = message.from_user
        return user.username, user.id, user.language_code, user.is_bot, message.text

    return None, None, None, None, None


def get_inline_message_full_info(
        *args: Any, **kwargs: Any
) -> Tuple[Union[str, None], Union[int, None], Union[bool, None]]:
    """
    Retrieves full information for inline handlers logs.

    Args:
        *args (Any): Variable length argument list.
        **kwargs (Any): Arbitrary keyword arguments.

    Returns:
        Tuple[Union[str, None], Union[int, None], Union[bool, None]]:
            A tuple containing the username, user ID, and is_bot flag of the message sender.
    """
    message = find_in_args(args, CallbackQuery) or find_in_kwargs(kwargs, CallbackQuery)

    if message:
        user = message.message.from_user
        return user.username, user.id, user.is_bot

    return None, None, None


def is_new_name_valid(new_name: str) -> bool:
    """
    Checks if the new name is valid.

    A valid name is between 1 and 64 characters long and does not contain only whitespace.

    Args:
        new_name (str): The new name to be validated.

    Returns:
        bool: True if the new name is valid, False otherwise.
    """
    if len(new_name) not in (1, 64):
        return False
    if new_name.isspace():
        return False
    return True


def is_valid_totp_code(totp_code: str) -> bool:
    """
    Checks if the provided TOTP code is valid.

    A valid TOTP code is a 6-digit number.

    Args:
        totp_code (str): The TOTP code to check.

    Returns:
        bool: True if the TOTP code is valid, False otherwise.
    """
    return len(totp_code) == 6 and totp_code.isdigit()


def is_bot_development(app_version: str) -> bool:
    """
    Check if the bot is in development mode.

    Args:
        app_version (str): The version of the bot application.

    Returns:
        bool: True if the bot is in development mode, False otherwise.
    """
    return len(app_version) > 6


@lru_cache(maxsize=None)
def is_running_in_docker() -> bool:
    """
    Determines whether the bot is running inside a Docker container.

    Returns:
        bool: True if the bot is running in a Docker container, False otherwise.
    """
    # Check for the presence of the Docker-specific cgroup file
    if os.path.exists("/.dockerenv"):
        return True

    # Check for Docker-specific process info
    try:
        with open("/proc/self/cgroup", "r") as f:
            for line in f:
                if "docker" in line:
                    return True
    except FileNotFoundError:
        pass

    # Check for Docker-specific environment variables
    if "DOCKER_CONTAINER" in os.environ:
        return True

    return False


def sanitize_exception(exception: Exception) -> str:
    """
    Sanitizes exception messages by replacing sensitive information with placeholders.

    Args:
        exception (Exception): The exception to sanitize.

    Returns:
        str: The sanitized exception message.
    """
    exception_str = str(exception)
    secret_map = {
        secret.get_secret_value(): "******************"
        for secret in (
            settings.bot_token.prod_token[0],
            settings.bot_token.dev_bot_token[0],
            settings.plugins_config.outline.api_url[0],
            settings.plugins_config.outline.cert[0],
        )
    }

    for secret, placeholder in secret_map.items():
        exception_str = exception_str.replace(secret, placeholder, 1)

    return exception_str


def generate_secret_token(secret_length: int = 32) -> str:
    """
    Generates a secret token for use in various parts of the bot.

    Args:
        secret_length (int, optional): The length of the secret token. Defaults to 32.

    Returns:
        str: The generated secret token.
    """
    return secrets.token_urlsafe(secret_length)
